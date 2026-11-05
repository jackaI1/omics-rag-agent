# Where I get the measurements

I downloaded the HPA v25.1 gene-level tissue tables on November 5, 2026. The files contain aggregate expression values by tissue, not donor records. I retained all tissues for these 20 gene symbols: ALB, INS, GCG, SST, TP53, BRCA1, BRCA2, EGFR, ERBB2, VEGFA, APOE, GFAP, MBP, CD3D, CD8A, MS4A1, ACTB, GAPDH, ACE2, and SLC2A1. I chose a mix of tissue markers, signalling genes, and common reference genes to make tissue comparisons useful while keeping the download-free example small.

| Source ID | Published archive | Retained rows |
| --- | --- | ---: |
| hpa | [HPA tissue RNA](https://www.proteinatlas.org/download/tsv/rna_tissue_hpa.tsv.zip) | 800 |
| gtex | [GTEx tissue RNA distributed by HPA](https://www.proteinatlas.org/download/tsv/rna_tissue_gtex.tsv.zip) | 720 |
| consensus | [Consensus tissue RNA](https://www.proteinatlas.org/download/tsv/rna_tissue_consensus.tsv.zip) | 1,020 |

I retain Ensembl gene ID, gene symbol, tissue name, and nTPM without changing the measurements. The extra source column identifies the archive. The SQLite row ID is a local citation key, stable for this extract and regenerated when the extract changes. A citation includes both the archive URL and gene/tissue identity; the URL downloads a table rather than linking to a particular line.

[The HPA methods page](https://www.proteinatlas.org/humanproteome/tissue/data) explains the normalization and source coverage. HPA consensus is the maximum normalized value from HPA and GTEx for the tissue, including the documented handling of sub-tissues. These are correlated sources, not three independent replications. Different cohorts and processing can produce different RNA measurements; the twofold comparison is not a biological finding or a significance test.

The [manifest](../src/omics_rag/data/manifest.json) records each original archive SHA-256, retrieval time, release label, extract SHA-256, and filtering method. The app verifies the bundled extract checksum at startup. To refresh from the public upstream files:

```sh
uv run python scripts/fetch_data.py
uv run pytest -q
```

The upstream URLs are mutable. Before accepting a refresh I check the release on the methods page, update the release labels if needed, and deliberately review any evaluation changes. The refresh script uses temporary download directories and removes them on success or failure. The frozen evaluation is not automatically rewritten by this script.

## Attribution

Data: The Human Protein Atlas, https://www.proteinatlas.org/, and GTEx as distributed and normalized by HPA, version 25.1. See [HPA licence and citation](https://www.proteinatlas.org/about/licence) and [external data sources](https://www.proteinatlas.org/about/licence#external_data). HPA states that copyrightable database content is available under CC BY 4.0, with third-party terms applying where relevant. I redistributed only aggregate tissue RNA values and changed the file organization and gene coverage.

Reference: Uhlén et al., *Tissue-based map of the human proteome*, Science 347:1260419 (2015), [doi:10.1126/science.1260419](https://doi.org/10.1126/science.1260419). The GTEx Consortium, *The GTEx Consortium atlas of genetic regulatory effects across human tissues*, Science 369:1318–1330 (2020), [doi:10.1126/science.aaz1776](https://doi.org/10.1126/science.aaz1776).
