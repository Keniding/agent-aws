#!/usr/bin/env bash
# Build build/lambda.zip with deps resolved from uv.lock (boto3 is vendored on purpose).
set -euo pipefail
rm -rf build && mkdir -p build/pkg
uv export --frozen --no-dev --no-hashes --no-emit-project -o build/requirements.txt
uv pip install --quiet --target build/pkg -r build/requirements.txt
cp src/app.py src/auth.py src/presignup.py src/index.html build/pkg/
(cd build/pkg && python3 -m zipfile -c ../lambda.zip .)
# Lambda runtime id = the Python uv resolved for this project
uv run python -c 'import sys;print(f"python{sys.version_info.major}.{sys.version_info.minor}")' \
  > build/runtime.txt
echo "built build/lambda.zip for $(cat build/runtime.txt)"
