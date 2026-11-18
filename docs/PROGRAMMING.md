# Programming in C and C++ with VS Code

Dictating source code, in Visual Studio Code, on Linux and on Windows. Back to the
[README](../README.md).

In a `.c`, `.cpp`, `.h` or `.hpp` file open in VS Code, dictation switches to rules made
for source code. Symbols are spoken, everything else is lower case, and spacing follows
the usual C style. Saying

> int line count equals zero semicolon

types `int line_count = 0;`, and

> for open bracket int i equals zero semicolon i less than ten semicolon i plus plus
> close bracket open brace

types `for (int i = 0; i < 10; i++) {`. "New line" keeps the indentation, goes a step
deeper after `{`, and a "close brace" on its own line steps back out.

[The demo video](https://youtu.be/RrhKpiO7YL8) shows a small C program being written
this way.

## What it pays attention to

- **Names already in the file are recognised.** If the file has `bufferSize`, saying
  "buffer size" types `bufferSize`. If it has `buffer_size`, that is what you get.
- **New names follow the file's style.** Several plain words in a row become one name,
  joined `like_this` or `likeThis` to match the rest of the file. Say "space" to keep two
  names apart: "widget space w" types `widget w`.
- **It knows where the cursor is.** Inside quotes, words keep their spaces, their
  apostrophes and their capitals: "quote don't panic quote" types `"don't panic"`.
  After `//`, or when you say "comment", what you say is written as a sentence and not
  as code, with a capital to start it and punctuation words as when writing English:
  "comment set x comma then y" types `// Set x, then y`. "New line" ends the comment,
  and what follows is code again. After `#include`, angle brackets hug the file name.
- **Operators are judged by what is around them.** "Minus" is a sign after `=` or
  `return` and a subtraction between two values. "Star" after a type is a pointer mark.
  An opening bracket hugs a function name but not `if` or `while`.
- **"And" and "or" between two values are the operators.** "If open bracket a and b
  close bracket" types `if (a && b)`, and "return a or b" types `return a || b`. In a
  name you are declaring, or one that is already in the file, they are part of the
  name: "bool black and white" types `bool black_and_white`.

## What to say

| Say | Types |
|---|---|
| open bracket, close bracket (or "paren") | `(` `)` |
| open brace, close brace | `{` `}` |
| open square, close square | `[` `]` |
| open angle, close angle, less than, greater than | `<` `>` |
| semicolon, comma, colon, dot, hash | `;` `,` `:` `.` `#` |
| equals, double equals, not equals | `=` `==` `!=` |
| plus, minus, times or star, slash, percent | `+` `-` `*` `/` `%` |
| less than or equal, greater than or equal | `<=` `>=` |
| plus plus, minus minus, plus equals, minus equals | `++` `--` `+=` `-=` |
| times equals, slash equals, percent equals | `*=` `/=` `%=` |
| and equals, pipe equals (or "or equals"), caret equals | `&=` `\|=` `^=` |
| and and, or or, bang | `&&` `\|\|` `!` |
| ampersand, pipe, caret, tilde | `&` `\|` `^` `~` |
| arrow, double colon | `->` `::` |
| shift left, shift right, shift left equals, shift right equals | `<<` `>>` `<<=` `>>=` |
| quote, single quote, backslash | `"` `'` `\` |
| underscore | `_`, joined to the words either side: "m underscore count" types `m_count` |
| comment | `//`, and the rest of the phrase as a sentence |
| space | a space between two names |
| camel case, pascal case, snake case, constant | the next name `likeThis`, `LikeThis`, `like_this`, `LIKE_THIS` |
| capital | a capital on the next word |
| literal | the next word as itself: "literal comma" types `comma` |

Numbers said in words become digits: "twenty one" is `21`, "one hundred" is `100`, "two
hundred and fifty six" is `256` and "four thousand and ninety six" is `4096`. A number
in sixteens is said figure by figure after "zero x": "zero x f f" is `0xff`.

Common names said as several words are known: "print f", "size of", "null pointer", "u
int 8 t", "c out", "end l". A type written with `_t` or after `::` ends there, so
"uint8_t value" and "std::string name" stay two words. The usual commands still work:
scratch that, undo that, backspace, select, the cursor moves and spell that.

## Better guesses with a C/C++ language server

If VS Code has a C/C++ extension that understands your code, such as
[clangd](https://marketplace.visualstudio.com/items?itemName=llvm-vs-code-extensions.vscode-clangd),
dictation uses what it knows. Before each phrase it asks what is in scope at the cursor:
which variables, functions and types exist there. Then:

- **A misheard name becomes the real one.** "Line counts" types `lineCount` if that is a
  variable here and nothing called `lineCounts` is. "Pointer" types `ptr`.
- **A name you are declaring is left alone.** After `int`, `char *`, `struct` or a type's
  name, what you say is new, so it is never changed to something that already exists.
- **Keywords and numbers are judged by position.** At the start of a statement "four" is
  `for`. Where a value is expected, "to" is `2` and "won" is `1`, unless a variable of
  that name exists.
- **Brackets said unclearly are understood.** "Open racket" is `(`.
- **The speech model is told what to listen for:** the names in scope, nearest first.

Without such an extension a misheard name is not put right, and the speech model isn't
told what is in scope: names are taken from the words in the file, as described above.
Keywords, numbers and brackets are judged the same either way. To add clangd on Ubuntu:
`sudo apt install clangd`, then install the clangd extension in VS Code.

## Switching it off

This is one setting, "VS Code C/C++ coding commands", in the Settings window. With it
off, C and C++ files are treated as plain text.

It is a first version: speech models are trained on prose, so expect to correct it more
often than when writing English. Source code is always heard by a Whisper model, even
when a Parakeet model is chosen for dictation, because Whisper can be told which names
to expect.
