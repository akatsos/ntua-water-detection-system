#!/bin/bash

echo "--- Started: $(date +"%T") ---"

venv_python="$(grep "Venv = " Code/config.ini | cut -d" " -f3)bin/python3"
app_path="$(grep "App = " Code/config.ini | cut -d" " -f3)Code/"

if pgrep -f "$venv_python ${app_path}sync_s1_products.py" > /dev/null; then
	echo "Syncing is running"
	exit
fi

if pgrep -f "$venv_python ${app_path}download_products.py" > /dev/null; then
        echo "Download is running"
        exit
fi

if pgrep -f "$venv_python ${app_path}preprocess_products.py" > /dev/null; then
        echo "Preprocess is running"
        exit
fi

if pgrep -f "$venv_python ${app_path}index_preprocessed.py" > /dev/null; then
        echo "Index is running"
        exit
fi

if pgrep -f "$venv_python ${app_path}predict_indexed.py" > /dev/null; then
        echo "Predict is running"
        exit
fi

cd ${app_path}
$venv_python "${app_path}sync_s1_products.py"
$venv_python "${app_path}download_products.py"
$venv_python "${app_path}preprocess_products.py"
$venv_python "${app_path}index_preprocessed.py"
$venv_python "${app_path}predict_indexed.py"

echo "--- Finished: $(date +"%T") ---"