"""Opt-in Responses-event collector for external inference adapters; no I/O."""

from copy import deepcopy


class ResponseStreamError(RuntimeError):
    """A transport outcome with received output, never a completed answer."""

    def __init__(self, kind, *, code=None, partial_output=None, received_output=None):
        super().__init__(kind)
        self.kind = kind
        self.code = deepcopy(code)
        self.partial_output = deepcopy(partial_output or [])
        self.received_output = deepcopy(received_output or [])


def _error_code(event):
    nested = event.get('error')
    nested = nested if isinstance(nested, dict) else {}
    for source, key in [(nested, 'code'), (event, 'code'), (nested, 'type')]:
        if source.get(key) is not None:
            return source[key]
    return None


class ResponseStream:
    """One trial's decoded event state, retained by the caller on cancellation."""

    def __init__(self):
        self.done = False
        self._succeeded = False
        self.terminal_event = None
        self._items = {}
        self._complete = set()
        self._text = {}
        self._terminal_output = None

    @property
    def received_output(self):
        items = deepcopy(self._items)
        for (index, content_index), chunks in sorted(self._text.items()):
            if index in self._complete:
                continue
            item = items.setdefault(index, {'type': 'message', 'role': 'assistant'})
            content = item.get('content', [])
            parts = {i: part for i, part in enumerate(content)} if isinstance(content, list) else {}
            parts[content_index] = {'type': 'output_text', 'text': ''.join(chunks)}
            item['content'] = [parts[key] for key in sorted(parts)]
        return [items[index] for index in sorted(items)]

    @property
    def partial_output(self):
        if self._terminal_output is not None:
            return deepcopy(self._terminal_output)
        return self.received_output

    def _fail(self, kind, code=None):
        self.done = True
        raise ResponseStreamError(kind, code=code, partial_output=self.partial_output,
                                  received_output=self.received_output)

    def _index(self, event, key):
        value = event.get(key)
        if type(value) is not int or value < 0:
            self._fail('invalid_event')
        return value

    def feed(self, event):
        """Return output on completed; return None while pending; raise on failure."""
        if self.done:
            raise ValueError('stream_already_terminal')
        if not isinstance(event, dict):
            self._fail('invalid_event')
        kind = event.get('type')
        if not isinstance(kind, str):
            self._fail('invalid_event')
        if kind in {'response.output_item.added', 'response.output_item.done'}:
            index = self._index(event, 'output_index')
            item = event.get('item')
            if not isinstance(item, dict):
                self._fail('invalid_event')
            self._items[index] = deepcopy(item)
            if kind == 'response.output_item.done':
                self._complete.add(index)
        elif kind == 'response.output_text.delta':
            index = self._index(event, 'output_index')
            content_index = self._index(event, 'content_index')
            if not isinstance(event.get('delta'), str):
                self._fail('invalid_event')
            if index in self._items and self._items[index].get('type') != 'message':
                self._fail('invalid_event')
            self._text.setdefault((index, content_index), []).append(event['delta'])
        elif kind in {'response.function_call_arguments.delta', 'response.function_call_arguments.done'}:
            index = self._index(event, 'output_index')
            key = 'delta' if kind.endswith('.delta') else 'arguments'
            if not isinstance(event.get(key), str):
                self._fail('invalid_event')
            item = self._items.setdefault(index, {'type': 'function_call'})
            if item.get('type') != 'function_call' or not isinstance(item.get('arguments', ''), str):
                self._fail('invalid_event')
            if event.get('item_id') is not None:
                item.setdefault('id', event['item_id'])
            item['arguments'] = (item.get('arguments', '') if key == 'delta' else '') + event[key]
        elif kind == 'error':
            self.terminal_event = kind
            self._fail(kind, _error_code(event))
        elif kind in {'response.completed', 'response.failed', 'response.incomplete'}:
            self.terminal_event = kind
            response = event.get('response')
            if not isinstance(response, dict):
                self._fail('invalid_event')
            output = response.get('output')
            if output is not None:
                if not isinstance(output, list) or any(not isinstance(item, dict) for item in output):
                    self._fail('invalid_event')
                self._terminal_output = deepcopy(output)
            if response.get('status') != kind.removeprefix('response.'):
                self._fail('terminal_status_mismatch')
            if kind != 'response.completed':
                code = _error_code(response)
                if code is None and isinstance(response.get('incomplete_details'), dict):
                    code = response['incomplete_details'].get('reason')
                self._fail(kind, code)
            self.done = True
            self._succeeded = True
            return self.partial_output
        return None

    def finish(self):
        """Classify EOF without a terminal event as a transport failure."""
        if not self._succeeded:
            self._fail('missing_terminal_event')
        return self.partial_output


def collect_response(events, *, state=None):
    """Consume decoded events only until a validated completed event, not EOF."""
    state = state if state is not None else ResponseStream()
    if state.done:
        raise ValueError('stream_already_terminal')
    try:
        for event in events:
            output = state.feed(event)
            if output is not None:
                return output
    except BaseException:
        state.done = True
        raise
    return state.finish()


async def collect_response_async(events, *, state=None):
    """Async equivalent; the caller owns response cleanup and the trial deadline."""
    state = state if state is not None else ResponseStream()
    if state.done:
        raise ValueError('stream_already_terminal')
    try:
        async for event in events:
            output = state.feed(event)
            if output is not None:
                return output
    except BaseException:
        state.done = True
        raise
    return state.finish()
