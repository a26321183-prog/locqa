import json
import os
import tempfile


def write_arb(directory: str, name: str, items: dict) -> str:
    """Write an ARB with a repeated @@comment, like the real files."""
    lines = ["{", '  "@@locale": "%s",' % name.split("_")[1].split(".")[0]]
    for i, (k, v) in enumerate(items.items()):
        if i % 2 == 0:
            lines.append('  "@@comment": "SECTION_%d",' % i)
        lines.append("  %s: %s," % (json.dumps(k), json.dumps(v, ensure_ascii=False)))
    lines[-1] = lines[-1].rstrip(",")
    lines.append("}")
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


class Tmp:
    def __enter__(self):
        self._d = tempfile.TemporaryDirectory()
        return self._d.name

    def __exit__(self, *a):
        self._d.cleanup()
