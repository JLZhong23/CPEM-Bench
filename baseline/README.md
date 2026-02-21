# CPEM

We evaluate three categories method on CPEM. 

1. Dictiona-based
```
# cliphen
pip install cliphen
python cliphen.py

# fasthpocr
git clone https://github.com/tudorgroza/fast_hpo_cr
```

2. Neural-based

```
# PhenoBERT
git clone https://github.com/EclipseCN/PhenoBERT.git

# PhenoTagger
git clone https://github.com/ncbi-nlp/PhenoTagger.git
huggingface-cli download --resume-download lingbionlp/PhenoTagger_v1.2 --local-dir PhenoTagger_v1.2

# PBTagger
git clone https://github.com/xiaohaomao/timgroup_disease_diagnosis.git
```

3. LLM-based

```
# RAG-HPOs
git clone https://github.com/PoseyPod/RAG-HPO.git

# REAL-BioCR
git clone https://github.com/dash-ka/REAL-BioCR.git
```