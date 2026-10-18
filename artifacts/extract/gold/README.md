# Gold transcriptions for CER

These files measure how well Nemotron Parse 3.5 read the scans (character error rate, CER).
Each gold file must match the scan image exactly, checked word by word by a person.

## How the gold files were made

1. `{row}.draft.txt` holds the first 180 words of Parse's text for the page. It is a starting point, not gold.
2. A person reads the draft next to the scan and corrects every difference, using the rules below.
3. The person saves the corrected file as `{row}.txt`. Only `.txt` files without `.draft` count for CER,
   so an unchecked draft can never score Parse against itself.

Read slowly: a wrong word that is already in the draft is easy to miss.

## Status

Only row 251 is transcribed (`0251.txt`, 177 words; `0251.draft.txt` is the Parse text it was corrected from).
The scans are 600 px wide, so they are slow and hard for people to read too, and the team chose
to stop at one page. Rows 523, 1327, 1649 and 2473 have no gold file; `coverage.json` lists them
under `cer.missing_gold_rows`.

## Pages

Picked with the issue #2 rule: 5 random `ok` pages, seed 7, from pages with at least 150 body words.

| Gold file | Scan |
| --- | --- |
| `0251.txt` | `data/raw/britannica/page-0251-69952e7c4a0f.jpg` |
| `0523.txt` | `data/raw/britannica/page-0523-a583606e375a.jpg` |
| `1327.txt` | `data/raw/britannica/page-1327-7d41b1db21d5.jpg` |
| `1649.txt` | `data/raw/britannica/page-1649-e6a1fc569876.jpg` |
| `2473.txt` | `data/raw/britannica/page-2473-b849fb7f25f2.jpg` |

## Rules

1. Start at the first body line: the top of the left column. Skip the page header (page number and running title).
   If the draft starts with header text, delete it.
2. Keep the first 150 to 200 words, in the order they are printed. If Parse put lines in the wrong order,
   fix the order. Stop at the end of a word; delete any extra draft text after that point.
3. Copy the words as printed, including old spellings. Do not correct the text.
4. Write the long s (ſ) as `s`.
5. Join a word split across two lines: "repre-" + "senting" becomes "representing".
6. Put one space between words. Line breaks do not matter.
7. Skip margin notes (short notes in the page margin) and footnote markers.
8. If you cannot read a word, type your best reading. Do not leave gaps.

The CER compares this text with the start of Parse's text for the same page.
Where you stop does not matter.
