# Окружение node + Playwright для шагов ночного прогона на DEV (крон не видит node из nvm). Подключать через `.`.
# та же версия node, что в обычной оболочке (nvm default), а не последняя по алфавиту (verify b2b-12)
DEF=$(cat "$HOME/.nvm/alias/default" 2>/dev/null)
NB=$(ls -d "$HOME"/.nvm/versions/node/v${DEF#v}*/bin 2>/dev/null | sort -V | tail -1)
[ -n "$NB" ] || NB=$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1)
export PATH="${NB:+$NB:}/usr/local/bin:$PATH"
export PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64 PLAYWRIGHT_BROWSERS_PATH="$HOME/.cache/ms-playwright"
