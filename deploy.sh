#!/bin/bash

rm -r build/ dist/
pyinstaller --onefile --add-data="ChessupRemote.glade:." ChessupRemote.py
pip freeze > requirements.txt
