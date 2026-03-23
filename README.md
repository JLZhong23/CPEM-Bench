# CPEM

## Environments
```
conda create -n cpem python=3.10 -y
conda activate cpem
pip install -r crawler/requirements.txt
pip install -r annotation/requirements.txt
```

## Usage
```
# crawler
python crawler/crawler.py
python crawler/crawlerWWW.py

# annotation
python annotation/main.py

# baseline (for evaluation, detailed information is available in baseline/README.md)
cd baseline
python eval.py --input all_data.json
# all_data.json include target data, ground truth and predicted results
```

## Downloads
[Google Drive](https://drive.google.com/drive/folders/1S2be8aanTULeGBSGWucy0RzQSJGsVHCL?usp=sharing)
