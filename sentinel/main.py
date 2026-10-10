# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""Entry point kept for existing MCP client configs: ``python -m sentinel.main``."""

from sentinel.adapters.mcp.server import main

if __name__ == "__main__":
    main()
