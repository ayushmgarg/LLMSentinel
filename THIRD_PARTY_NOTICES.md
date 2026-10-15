# Third-party data notices

The files under `data/processed/` combine examples written for this project (CC0-1.0) with
records taken from the third-party datasets below. Each record names its source in the
`source_dataset` field (`builtin`, `bipia`, `injecagent`). The original repositories are not
included in this repository.

| Source | What we use | Licence | Records derived from it |
|---|---|---|---|
| [BIPIA](https://github.com/microsoft/BIPIA) | Attack instructions (`text_attack_*.json`) and the EmailQA and TableQA context files | MIT, Copyright (c) Microsoft Corporation | records with `source_dataset: bipia` |
| [OpenAI Evals](https://github.com/openai/evals), via BIPIA | The e-mails used as EmailQA contexts | MIT, Copyright (c) 2023 OpenAI | `bipia` records whose `group_id` contains `email/` |
| [WikiTableQuestions](https://github.com/ppasupat/WikiTableQuestions) (Pasupat and Liang, 2015), via BIPIA | The tables used as TableQA contexts | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) | `bipia` records whose `group_id` contains `table/` |
| [InjecAgent](https://github.com/uiuc-kang-lab/InjecAgent) | Tool-response texts with injected instructions | MIT, Copyright (c) 2023 Qiusi Zhan | records with `source_dataset: injecagent` |

**Changes made to the third-party text:** attack instructions were inserted into contexts;
text was normalised (Unicode folding, removal of invisible characters, decoding of encoded
payloads); records were relabelled, deduplicated and split; some records were cut to the
injected span, re-inserted into other contexts (`data/processed/augmented/`), or rewritten by
a language model (`data/processed/paraphrase/`).

**Share-alike.** Records derived from WikiTableQuestions, including their modified versions,
are licensed under CC BY-SA 4.0, as that licence requires. Everything else in
`data/processed/` is available under the licence of its source shown above, or CC0-1.0 for
`builtin` records.

---

## BIPIA

```
MIT License

Copyright (c) Microsoft Corporation.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE
```

BIPIA's licence notes that its benchmark folder contains datasets under their own licences;
the two we use are listed above (OpenAI Evals, WikiTableQuestions).

## OpenAI Evals

```
MIT License

Copyright (c) 2023 OpenAI

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## WikiTableQuestions

Panupong Pasupat and Percy Liang. *Compositional Semantic Parsing on Semi-Structured Tables.*
ACL 2015. Dataset: <https://github.com/ppasupat/WikiTableQuestions>. Licensed under the
Creative Commons Attribution-ShareAlike 4.0 International License:
<https://creativecommons.org/licenses/by-sa/4.0/legalcode>. Provided as is, without
warranties.

## InjecAgent

```
MIT License

Copyright (c) 2023 Qiusi Zhan

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
