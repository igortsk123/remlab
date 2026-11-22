#!/bin/bash
# xvfb-run без утечек (T-20261120-162): те же аргументы, что у xvfb-run; Xvfb не наследует fd замка heavy-slot и уходит вместе с
# xvfb-run (подмена Xvfb из xvfb-bin/ — см. комментарий в ней). Все запуски Blender под xvfb идут ЧЕРЕЗ ЭТОТ скрипт.
HERE=$(cd "$(dirname "$0")" && pwd)
PATH="$HERE/xvfb-bin:$PATH" exec xvfb-run "$@"
