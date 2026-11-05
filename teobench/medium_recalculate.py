"""Trusted container helper: original UNO functions, explicit write receipts."""
import json
from pathlib import Path
import runpy
import sys


def main():
    module=runpy.run_path(sys.argv[1])
    directory=Path(sys.argv[2]);names=json.loads(sys.argv[3])
    files=[directory/name for name in names]
    before={p.name:p.stat().st_mtime_ns for p in files}
    if not module['start_libreoffice_service']():
        raise RuntimeError('official_libreoffice_service_unavailable')
    try:
        # The upstream CLI silently filters filenames. Calling its original
        # batch function explicitly preserves its calculation/save protocol.
        module['batch_open_files']([str(p) for p in files])
        changed={p.name:p.stat().st_mtime_ns!=before[p.name] for p in files}
        if not all(changed.values()):
            raise RuntimeError('official_recalculation_did_not_replace_every_workbook')
        (directory/'recalculation.json').write_text(json.dumps({'replaced':changed}))
    finally:module['stop_libreoffice_service']()


if __name__=='__main__':main()
