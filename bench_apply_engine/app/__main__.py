from . import __doc__

# Allow `python -m app` if needed during local development.
if __name__ == "__main__":
    print(__doc__ or "Standalone bench apply engine package")
