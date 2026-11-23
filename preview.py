"""A separate process owns the preview document handles and render buffers."""

from collections import OrderedDict
import multiprocessing as mp
import engine as e


def serve(pipe):
    sources = OrderedDict()
    try:
        while True:
            leaf, zoom, thumbnail = pipe.recv()
            build = None
            try:
                if leaf.path and not (leaf.turn or leaf.crop or leaf.marks):
                    key = (leaf.path, leaf.password)
                    if key not in sources:
                        sources[key] = e.open_pdf(*key)
                    sources.move_to_end(key)
                    if len(sources) > 4:
                        sources.popitem(last=False)[1].close()
                    page = sources[key][leaf.index]
                else:
                    build = e.Builder()
                    page = build.add(leaf)
                rect = page.rect
                scale = 60 / max(rect.width, rect.height) if thumbnail else zoom
                pix = page.get_pixmap(matrix=e.pdf.Matrix(scale, scale), alpha=False)
                pipe.send((pix.tobytes("png"), tuple(rect), None))
            except Exception as exc:
                pipe.send((None, None, str(exc)))
            finally:
                if build is not None:
                    build.stack.close()
    except (EOFError, BrokenPipeError):
        pass
    finally:
        for doc in sources.values():
            doc.close()
        pipe.close()


class Renderer:
    def __init__(self):
        self.pipe, child = mp.Pipe()
        self.proc = mp.Process(target=serve, args=(child,), daemon=True)
        self.proc.start()
        child.close()
        self.pending = None

    def request(self, key, leaf, zoom, thumbnail=False):
        self.pipe.send((leaf, zoom, thumbnail))
        self.pending = key

    def stop(self):
        self.proc.terminate()
        self.proc.join()
        self.proc.close()
        self.pipe.close()
