# Gold transcriptions for CER

These files measure how well Nemotron Parse 3.5 read the scans (character error rate, CER).
A person types each file from the scan image. Never copy text from Parse output.

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
2. Type the first 150 to 200 words, in order. Stop at the end of a word.
3. Copy the words as printed, including old spellings. Do not correct the text.
4. Write the long s (ſ) as `s`.
5. Join a word split across two lines: "repre-" + "senting" becomes "representing".
6. Put one space between words. Line breaks do not matter.
7. Skip margin notes (short notes in the page margin) and footnote markers.
8. If you cannot read a word, type your best reading. Do not leave gaps.

The CER compares this text with the start of Parse's text for the same page.
Where you stop does not matter.
