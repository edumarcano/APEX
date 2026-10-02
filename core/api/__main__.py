"""Run the local API server through the lifecycle-owning host."""

import sys

from core.backend_host import main


if __name__ == "__main__":
    raise SystemExit(main(["serve", "--standalone", *sys.argv[1:]]))
