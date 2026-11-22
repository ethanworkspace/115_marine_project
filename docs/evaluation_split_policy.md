# Evaluation Corpus Split Policy (draft)

This policy defines future split construction only. Phase 8 does not assign or lock question records to a final test set.

## Grouping unit

Use source document identity plus version as the primary grouping key. All chunks from one document/version, including adjacent pages, parent-child pairs, exact copies and derived OCR/conversion outputs, stay in one split. When documents are exact duplicates or duplicate-source records, group them together using canonical document mapping. Do not split neighboring chunks from one source across tuning and test sets.

## Splits

- `development`: representative species and topic coverage used for prompt/retrieval development.
- `locked_test`: held aside until system configuration is frozen; access limited to final evaluation.
- `source_holdout`: documents or organizations absent from development to measure source generalization. Prefer source organization as holdout grouping when sufficient independent organizations exist.

## Assignment procedure

1. Freeze document manifest/version and canonical duplicate mappings.
2. Group by canonical document/version; merge all derived copies and related duplicate sources.
3. Assign groups, not individual chunks/questions. Stratify only at group level to preserve species/category coverage.
4. Record seed, grouping keys, source holdout organization, corpus checksum, and assignment date in a split manifest.
5. Audit overlap by canonical document ID, source checksum, source URL/version and exact chunk checksum before locking.
6. Do not use locked-test failures to tune retrieval, prompt, embedding, or reranker; changes trigger a new evaluation version.

If a category has too few independent source groups, report the limitation instead of leaking the same source across splits. Final proportions and test locking require a reviewed Gold set and are deferred.
