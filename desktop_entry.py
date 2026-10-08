"""PyInstaller entry point."""
import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from azurai.desktop import entrypoint
    entrypoint()
