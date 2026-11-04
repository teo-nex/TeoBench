import asyncio
import unittest

from teobench.response_stream import (
    ResponseStream, ResponseStreamError, collect_response, collect_response_async,
)


def message(text):
    return {'type': 'message', 'role': 'assistant',
            'content': [{'type': 'output_text', 'text': text}]}


def terminal(status='completed', output=None, **fields):
    response = {'status': status, 'output': output}
    response.update(fields)
    return {'type': 'response.' + status, 'response': response}


def delta(text, output_index=0, content_index=0):
    return {'type': 'response.output_text.delta', 'delta': text,
            'output_index': output_index, 'content_index': content_index}


class ResponseStreamTests(unittest.TestCase):
    def test_completed_does_not_request_eof(self):
        def events():
            yield terminal(output=[message('source code')])
            raise AssertionError('Reader continued after the completed event')
        self.assertEqual(collect_response(events()), [message('source code')])

    def test_empty_completed_output_is_still_terminal(self):
        def events():
            yield terminal(output=[])
            raise AssertionError('An empty completed result must stop the reader')
        self.assertEqual(collect_response(events()), [])

    def test_explicit_empty_terminal_output_does_not_promote_received_fragments(self):
        for status in ['completed', 'failed', 'incomplete']:
            with self.subTest(status=status):
                state = ResponseStream()
                state.feed(delta('received prefix'))
                if status == 'completed':
                    self.assertEqual(state.feed(terminal(status=status, output=[])), [])
                else:
                    with self.assertRaises(ResponseStreamError) as caught:
                        state.feed(terminal(status=status, output=[]))
                    self.assertEqual(caught.exception.partial_output, [])
                    self.assertEqual(caught.exception.received_output, [message('received prefix')])
                self.assertEqual(state.partial_output, [])
                self.assertEqual(state.received_output, [message('received prefix')])

    def test_terminal_output_is_authoritative_and_copied(self):
        state = ResponseStream()
        state.feed(delta('prefix'))
        event = terminal(output=[message('complete source')])
        output = state.feed(event)
        event['response']['output'][0]['content'][0]['text'] = 'changed input'
        output[0]['content'][0]['text'] = 'changed result'
        self.assertEqual(state.partial_output, [message('complete source')])
        self.assertEqual(state.received_output, [message('prefix')])

    def test_null_output_uses_received_complete_item(self):
        item = {'type': 'response.output_item.done', 'output_index': 0,
                'item': message('received source')}
        self.assertEqual(collect_response([item, terminal()]), [message('received source')])

    def test_null_output_uses_received_text_deltas(self):
        self.assertEqual(collect_response([delta('first'), delta(' second'), terminal()]),
                         [message('first second')])

    def test_content_indices_preserve_multiple_text_parts(self):
        output = collect_response([delta('first', content_index=0),
                                   delta('second', content_index=1), terminal()])
        self.assertEqual([part['text'] for part in output[0]['content']], ['first', 'second'])

    def test_sparse_index_does_not_allocate_missing_parts(self):
        state = ResponseStream()
        state.feed(delta('one received part', content_index=10**9))
        self.assertEqual(state.received_output, [message('one received part')])

    def test_done_item_overrides_shorter_delta(self):
        item = {'type': 'response.output_item.done', 'output_index': 0,
                'item': message('full item text')}
        self.assertEqual(collect_response([delta('prefix'), item, terminal()]),
                         [message('full item text')])

    def test_failed_and_incomplete_never_return_success(self):
        for status in ['failed', 'incomplete']:
            with self.subTest(status=status):
                with self.assertRaises(ResponseStreamError) as caught:
                    collect_response([delta('received fragment'), terminal(status=status)])
                self.assertEqual(caught.exception.kind, 'response.' + status)
                self.assertEqual(caught.exception.partial_output, [message('received fragment')])

    def test_event_status_mismatch_is_rejected(self):
        for kind, status in [('response.failed', 'completed'),
                             ('response.incomplete', 'completed'),
                             ('response.completed', 'failed')]:
            with self.subTest(kind=kind, status=status):
                event = {'type': kind, 'response': {'status': status, 'output': []}}
                state = ResponseStream()
                with self.assertRaisesRegex(ResponseStreamError, 'terminal_status_mismatch'):
                    state.feed(event)
                with self.assertRaises(ResponseStreamError):
                    state.finish()

    def test_nested_error_code_and_top_level_fallback(self):
        for event, expected in [
            ({'type': 'error', 'code': 'outer', 'error': {'code': 'inner'}}, 'inner'),
            ({'type': 'error', 'code': 'outer', 'error': {'message': 'detail'}}, 'outer'),
            ({'type': 'error', 'error': {'type': 'server_error'}}, 'server_error'),
        ]:
            with self.subTest(event=event):
                with self.assertRaises(ResponseStreamError) as caught:
                    collect_response([event])
                self.assertEqual(caught.exception.code, expected)

    def test_failed_response_keeps_its_error_code(self):
        with self.assertRaises(ResponseStreamError) as caught:
            collect_response([terminal(status='failed', error={'code': 'backend_busy'})])
        self.assertEqual(caught.exception.code, 'backend_busy')

    def test_incomplete_keeps_its_reason(self):
        with self.assertRaises(ResponseStreamError) as caught:
            collect_response([terminal(status='incomplete',
                                       incomplete_details={'reason': 'max_output_tokens'})])
        self.assertEqual(caught.exception.code, 'max_output_tokens')

    def test_failure_retains_terminal_and_received_output(self):
        with self.assertRaises(ResponseStreamError) as caught:
            collect_response([delta('prefix'), terminal(status='failed',
                                                        output=[message('full terminal source')])])
        self.assertEqual(caught.exception.partial_output, [message('full terminal source')])
        self.assertEqual(caught.exception.received_output, [message('prefix')])

    def test_eof_without_terminal_is_a_transport_error(self):
        with self.assertRaisesRegex(ResponseStreamError, 'missing_terminal_event') as caught:
            collect_response([delta('partial source')])
        self.assertEqual(caught.exception.partial_output, [message('partial source')])

    def test_partial_function_call_and_argument_deltas_are_retained(self):
        frames = [
            {'type': 'response.output_item.added', 'output_index': 0,
             'item': {'type': 'function_call', 'id': 'synthetic-item',
                      'call_id': 'synthetic-call', 'name': 'lookup', 'arguments': ''}},
            {'type': 'response.function_call_arguments.delta', 'output_index': 0,
             'delta': '{"id":'},
            {'type': 'response.function_call_arguments.delta', 'output_index': 0,
             'delta': '"unfinished'},
        ]
        with self.assertRaises(ResponseStreamError) as caught:
            collect_response(frames)
        item = caught.exception.received_output[0]
        self.assertEqual(item['name'], 'lookup')
        self.assertEqual(item['call_id'], 'synthetic-call')
        self.assertEqual(item['arguments'], '{"id":"unfinished')

    def test_done_arguments_replace_deltas(self):
        state = ResponseStream()
        state.feed({'type': 'response.function_call_arguments.delta', 'output_index': 0,
                    'item_id': 'synthetic-item', 'delta': '{"id":'})
        state.feed({'type': 'response.function_call_arguments.done', 'output_index': 0,
                    'arguments': '{"id":"synthetic-node"}'})
        self.assertEqual(state.received_output[0]['arguments'], '{"id":"synthetic-node"}')

    def test_error_text_does_not_echo_provider_message_or_metadata(self):
        secret = 'synthetic-private-value-not-a-real-credential'
        frames = [{'type': 'response.created', 'response': {'safety_identifier': secret}},
                  {'type': 'error', 'code': secret, 'message': secret}]
        state = ResponseStream()
        with self.assertRaises(ResponseStreamError) as caught:
            collect_response(frames, state=state)
        self.assertEqual(str(caught.exception), 'error')
        self.assertEqual(caught.exception.code, secret)
        self.assertNotIn(secret, repr(state.__dict__))

    def test_snapshots_do_not_mutate_received_state(self):
        state = ResponseStream()
        state.feed(delta('actual fragment'))
        snapshot = state.received_output
        snapshot[0]['content'][0]['text'] = 'changed copy'
        self.assertEqual(state.received_output, [message('actual fragment')])

    def test_malformed_events_fail_closed(self):
        cases = [None, [], {'type': []}, {'type': 'response.completed', 'response': None},
                 {'type': 'response.completed', 'response': {'status': 'completed', 'output': 'text'}},
                 {'type': 'response.completed', 'response': {'status': 'completed', 'output': [1]}},
                 delta(42), delta('text', output_index=True), delta('text', output_index=-1),
                 {'type': 'response.output_item.done', 'output_index': 0, 'item': None}]
        for event in cases:
            with self.subTest(event=event):
                with self.assertRaises(ResponseStreamError):
                    collect_response([event])

    def test_state_cannot_be_reused_for_another_attempt(self):
        state = ResponseStream()
        collect_response([terminal(output=[])], state=state)
        with self.assertRaisesRegex(ValueError, 'stream_already_terminal'):
            collect_response([], state=state)
        with self.assertRaisesRegex(ValueError, 'stream_already_terminal'):
            state.feed(delta('another attempt'))

    def test_iterator_error_keeps_type_and_state_without_retry(self):
        state = ResponseStream()
        def events():
            yield delta('received before read error')
            raise OSError('synthetic read error')
        with self.assertRaisesRegex(OSError, 'synthetic read error'):
            collect_response(events(), state=state)
        self.assertTrue(state.done)
        self.assertEqual(state.partial_output, [message('received before read error')])


class AsyncResponseStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_completed_returns_while_connection_stays_open(self):
        resumed_after_terminal = []
        async def events():
            yield terminal(output=[message('complete source')])
            resumed_after_terminal.append(True)
            await asyncio.Future()
        source = events()
        try:
            output = await asyncio.wait_for(collect_response_async(source), 1)
        finally:
            await source.aclose()
        self.assertEqual(output, [message('complete source')])
        self.assertEqual(resumed_after_terminal, [])

    async def test_failed_returns_error_without_waiting_for_eof(self):
        async def events():
            yield terminal(status='failed', output=[message('partial source')])
            raise AssertionError('Reader continued after a failed terminal event')
        source = events()
        try:
            with self.assertRaises(ResponseStreamError):
                await collect_response_async(source)
        finally:
            await source.aclose()

    async def test_timeout_preserves_caller_owned_state(self):
        state = ResponseStream()
        async def events():
            yield delta('received before timeout')
            await asyncio.Future()
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(collect_response_async(events(), state=state), 0.03)
        self.assertTrue(state.done)
        self.assertEqual(state.partial_output, [message('received before timeout')])

    async def test_cancellation_is_not_converted_to_a_completed_answer(self):
        state = ResponseStream()
        ready = asyncio.Event()
        async def events():
            yield delta('received before cancellation')
            ready.set()
            await asyncio.Future()
        task = asyncio.create_task(collect_response_async(events(), state=state))
        await asyncio.wait_for(ready.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(state.done)
        self.assertEqual(state.partial_output, [message('received before cancellation')])

    async def test_async_eof_is_not_completion(self):
        async def events():
            yield delta('partial source')
        with self.assertRaisesRegex(ResponseStreamError, 'missing_terminal_event'):
            await collect_response_async(events())
