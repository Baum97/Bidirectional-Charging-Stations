# Try to start an existing container, if it exists
docker start -a -i "latex-container"

if ($LASTEXITCODE -ne 0) {
  # The latex-builder image doesn't exist, so run it explicitly
  $ROOT_DIR="$PSScriptRoot"

  docker run -it `
    --mount "type=bind,source=$ROOT_DIR,target=/bericht" `
    --name "latex-builder" `
    blang/latex:ctanfull /bin/bash
}
