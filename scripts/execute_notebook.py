"""Exécuter le notebook avec le Python courant, sans installer de kernel global."""

import argparse
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import nbformat
from jupyter_client import KernelManager
from jupyter_client.kernelspec import KernelSpecManager
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[1]


def execute(path: Path) -> None:
    """Un kernel temporaire utilise précisément sys.executable et ses paquets."""
    notebook = nbformat.read(path, as_version=4)
    with TemporaryDirectory(prefix="execution-cost-kernel-") as kernel_root:
        specification = Path(kernel_root) / "execution-cost-analytics"
        specification.mkdir()
        (specification / "kernel.json").write_text(
            json.dumps(
                {
                    "argv": [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
                    "display_name": "Execution cost analytics",
                    "language": "python",
                }
            ),
            encoding="utf-8",
        )
        manager = KernelManager(
            kernel_name="execution-cost-analytics",
            kernel_spec_manager=KernelSpecManager(kernel_dirs=[kernel_root]),
        )
        client = NotebookClient(
            notebook,
            km=manager,
            timeout=600,
            resources={"metadata": {"path": str(ROOT)}},
        )
        try:
            client.execute()
        finally:
            if manager.has_kernel:
                manager.shutdown_kernel(now=True)
    # Le kernel temporaire n'est pas requis pour ouvrir ce notebook ailleurs.
    notebook.metadata["kernelspec"] = {
        "display_name": "Python 3",
        "language": "python",
        "name": "python3",
    }
    nbformat.write(notebook, path)
    print(f"Notebook exécuté et enregistré : {path.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Exécuter les notebooks avec le Python courant.")
    parser.add_argument("--notebook", type=Path)
    args = parser.parse_args()
    paths = (
        [args.notebook.resolve()] if args.notebook else sorted((ROOT / "notebooks").glob("*.ipynb"))
    )
    for path in paths:
        execute(path)


if __name__ == "__main__":
    main()
