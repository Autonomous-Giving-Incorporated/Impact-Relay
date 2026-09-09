from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class PrefixHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path: str) -> str:
        if path == "/impact-relay":
            path = "/"
        elif path.startswith("/impact-relay/"):
            path = path[len("/impact-relay") :]
        return super().translate_path(path)


ThreadingHTTPServer(("127.0.0.1", 4174), partial(PrefixHandler, directory=".")).serve_forever()
