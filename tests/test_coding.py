import unittest

from dictation.coding import (
    alike, declaring, fit_code, join, known_names, loose_symbol, name_style, position, prompt,
    snap, sound, spoken, tokens, where,
)
from dictation.formatting import LINE


def code(raw, before="", after="", names=()):
    ins = fit_code(raw, before, after, names)
    return before[: len(before) - ins.delete_before] + ins.text + after


class Statements(unittest.TestCase):
    def test_include(self):
        self.assertEqual(code("Hash include open angle stdio dot h close angle."), "#include <stdio.h>")
        self.assertEqual(code("hash include quote my header dot h quote"), '#include "my header.h"')
        self.assertEqual(code("hash define max size 100"), "#define max_size 100")

    def test_declarations(self):
        self.assertEqual(code("Int count equals zero, semicolon."), "int count = 0;")
        self.assertEqual(code("int main open bracket close bracket open brace"), "int main() {")
        self.assertEqual(code("char star star arg v"), "char **argv")
        self.assertEqual(code("const char star name equals quote bob quote semicolon"),
                         'const char *name = "bob";')
        self.assertEqual(code("unsigned long total semicolon"), "unsigned long total;")
        self.assertEqual(code("u int 8 t flags semicolon"), "uint8_t flags;")

    def test_expressions(self):
        self.assertEqual(code("x equals count plus one semicolon", names=["count"]), "x = count + 1;")
        self.assertEqual(code("return minus one semicolon"), "return -1;")
        self.assertEqual(code("y equals x minus one"), "y = x - 1")
        self.assertEqual(code("y equals a times b"), "y = a * b")
        self.assertEqual(code("star p equals ampersand x semicolon"), "*p = &x;")
        self.assertEqual(code("a open square i close square plus equals star p"), "a[i] += *p")
        self.assertEqual(code("i plus plus semicolon"), "i++;")
        self.assertEqual(code("plus plus i"), "++i")
        self.assertEqual(code("p arrow next equals null pointer semicolon"), "p->next = nullptr;")
        self.assertEqual(code("x equals a question mark b colon c semicolon"), "x = a ? b : c;")
        self.assertEqual(code("n equals size of open bracket buffer close bracket"), "n = sizeof(buffer)")

    def test_control_flow(self):
        self.assertEqual(
            code("for open bracket int i equals zero semicolon i less than n semicolon "
                 "i plus plus close bracket open brace"),
            "for (int i = 0; i < n; i++) {")
        self.assertEqual(code("if open bracket x not equals y and and bang done close bracket"),
                         "if (x != y && !done)")
        self.assertEqual(code("while open bracket true close bracket"), "while (true)")
        self.assertEqual(code("case twenty one colon"), "case 21:")
        self.assertEqual(code("else if open bracket"), "else if (")

    def test_a_for_loop_as_the_recogniser_writes_it(self):
        want = "for (int i = 0; i < 10; i++)"
        for heard in (
            "4 open bracket int i equals zero semicolon i is less than 10 semicolon i plus plus close bracket",
            "4(int i=0;i is < 10;i++)",
            "four open bracket int i equals 0 semicolon i less than ten semicolon i plus plus close bracket",
            "for open bracket int i equals 0 semicolon i is less than ten semicolon i plus plus close bracket",
        ):
            self.assertEqual(code(heard, before="    "), "    " + want, heard)
        self.assertEqual(code("x equals 4 semicolon"), "x = 4;")
        self.assertEqual(code("if open bracket count is greater than or equal to 4 close bracket"),
                         "if (count >= 4)")
        self.assertEqual(code("bool is done equals true semicolon"), "bool is_done = true;")

    def test_calls_and_strings(self):
        self.assertEqual(
            code("print f open bracket quote hello comma world backslash n quote close bracket semicolon"),
            'printf("hello, world\\n");')
        self.assertEqual(code("print f open bracket quote value percent d quote comma x close bracket"),
                         'printf("value %d", x)')
        self.assertEqual(code("foo open bracket a comma b close bracket semicolon"), "foo(a, b);")

    def test_escapes_in_strings(self):
        want = 'printf("hello\\n");'
        for said in ("backslash n", "backslash and", "back slash en", "new line", "backslash in"):
            self.assertEqual(
                code(f"print f open bracket quote hello {said} quote close bracket semicolon"),
                want, said)
        self.assertEqual(code("quote a tab b backslash zero quote"), '"a\\tb\\0"')
        self.assertEqual(code("new line quote", before='puts("done'), 'puts("done\\n"')
        self.assertEqual(code("char c equals single quote backslash n single quote semicolon"),
                         "char c = '\\n';")
        self.assertEqual(code("open brace new line x"), "{" + LINE + "x")  # outside a string: a real break

    def test_cpp(self):
        self.assertEqual(code("std double colon vector open angle int close angle values semicolon"),
                         "std::vector<int> values;")
        self.assertEqual(code("std double colon c out shift left quote hi quote shift left std double colon end l semicolon"),
                         'std::cout << "hi" << std::endl;')
        self.assertEqual(code("static cast open angle int close angle open bracket x close bracket"),
                         "static_cast<int>(x)")
        self.assertEqual(code("if open bracket a less than b close bracket"), "if (a < b)")

    def test_comment_and_breaks(self):
        self.assertEqual(code("comment set the count to zero"), "// Set the count to zero")
        self.assertEqual(code("open brace new line return zero semicolon"), "{" + LINE + "return 0;")

    def test_whisper_writing_symbols_itself(self):
        self.assertEqual(code("int x = 5;"), "int x = 5;")
        self.assertEqual(code("#include <stdio.h>"), "#include <stdio.h>")
        self.assertEqual(code("i++;"), "i++;")


class Names(unittest.TestCase):
    def test_spoken(self):
        self.assertEqual(spoken("bufferSize"), ("buffer", "size"))
        self.assertEqual(spoken("buffer_size"), ("buffer", "size"))
        self.assertEqual(spoken("MAX_LEN"), ("max", "len"))
        self.assertEqual(spoken("uint8"), ("uint", "8"))

    def test_names_in_the_file_are_recognised(self):
        self.assertEqual(code("buffer size equals zero", names=["bufferSize"]), "bufferSize = 0")
        self.assertEqual(code("buffer size equals max len", names=["buffer_size", "MAX_LEN"]),
                         "buffer_size = MAX_LEN")
        self.assertEqual(code("buffersize equals zero", names=["bufferSize"]), "bufferSize = 0")
        self.assertEqual(code("count total", names=["count", "total"]), "count total")

    def test_new_names_follow_the_files_style(self):
        self.assertEqual(code("int line count semicolon", names=["my_var", "other_thing"]), "int line_count;")
        self.assertEqual(code("int line count semicolon", names=["myVar", "otherThing"]), "int lineCount;")
        self.assertEqual(code("int buffer size semicolon", names=["size"]), "int buffer_size;")
        self.assertEqual(name_style([]), "snake")

    def test_asking_for_a_style(self):
        self.assertEqual(code("camel case my new value equals 3.14 semicolon"), "myNewValue = 3.14;")
        self.assertEqual(code("pascal case my class open brace"), "MyClass {")
        self.assertEqual(code("constant max buffer size"), "MAX_BUFFER_SIZE")
        self.assertEqual(join(["a", "b"], "smash"), "ab")

    def test_space_keeps_names_apart(self):
        self.assertEqual(code("widget space w semicolon"), "widget w;")
        self.assertEqual(code("widget w semicolon"), "widget_w;")

    def test_literal_and_capital(self):
        self.assertEqual(code("literal comma equals one"), "comma = 1")
        self.assertEqual(code("capital widget space w"), "Widget w")

    def test_prompt_lists_names_as_words(self):
        self.assertTrue(prompt(["bufferSize", "count"]).endswith("buffer size count"))
        self.assertEqual(known_names(["bufferSize"])[("buffer", "size")], "bufferSize")


SCOPE = {"origin": "variable", "argc": "variable", "argv": "variable", "lineCount": "variable",
         "ptr": "variable", "bufferSize": "variable", "helper_value": "function",
         "main": "function", "Point": "type", "char": "keyword", "struct": "keyword",
         "count": "variable", "total": "variable", "len": "variable"}


def scoped(raw, before="    "):
    return fit_code(raw, before, "", list(SCOPE), SCOPE).text


class WithTheLanguageServer(unittest.TestCase):
    """What changes when the editor says what is in scope at the cursor."""

    def test_misheard_names_become_the_real_ones(self):
        self.assertEqual(scoped("line counts plus plus semicolon"), "lineCount++;")
        self.assertEqual(scoped("buffer sighs equals zero semicolon"), "bufferSize = 0;")
        self.assertEqual(scoped("if open bracket pointer equals equals null close bracket"),
                         "if (ptr == NULL)")
        self.assertEqual(scoped("total equals length semicolon"), "total = len;")

    def test_a_name_being_declared_is_left_alone(self):
        self.assertEqual(scoped("int counter equals zero semicolon"), "int counter = 0;")
        self.assertEqual(scoped("char star pointer semicolon"), "char *pointer;")
        self.assertEqual(scoped("struct shape info open brace"), "struct shapeInfo {")
        self.assertEqual(scoped("Point origins semicolon"), "Point origins;")

    def test_compiler_names_are_ignored(self):
        scope = dict(SCOPE, __LINE__="keyword", __COUNTER__="variable", _Nonnull="keyword")
        self.assertEqual(fit_code("int line counter equals zero semicolon", "    ", "",
                                  ["line_count", "__LINE__"], scope).text, "int line_counter = 0;")
        self.assertNotIn("counter", prompt([], {"__COUNTER__": "variable"}))

    def test_unrelated_new_names_are_left_alone(self):
        self.assertEqual(scoped("banana equals one semicolon"), "banana = 1;")
        self.assertEqual(scoped("camel case line counts equals one"), "lineCounts = 1")

    def test_without_a_language_server_nothing_is_corrected(self):
        self.assertEqual(fit_code("line counts plus plus", "", "", ["lineCount"]).text, "lineCounts++")
        self.assertEqual(fit_code("pointer equals null", "", "", ["ptr"]).text, "pointer = NULL")

    def test_keywords_at_the_start_of_a_statement(self):
        self.assertEqual(scoped("four open bracket int i equals zero semicolon"), "for (int i = 0;")
        self.assertEqual(scoped("wile open bracket true close bracket"), "while (true)")
        self.assertEqual(scoped("in total lines equals zero semicolon"), "int totalLines = 0;")
        self.assertEqual(scoped("avoid print thing open bracket close bracket"), "void printThing()")
        self.assertEqual(fit_code("x equals four semicolon", "", "").text, "x = 4;")

    def test_numbers_where_a_value_is_expected(self):
        self.assertEqual(scoped("total equals count times to semicolon"), "total = count * 2;")
        self.assertEqual(scoped("total equals len plus for semicolon"), "total = len + 4;")
        self.assertEqual(scoped("count plus equals won semicolon"), "count += 1;")
        self.assertEqual(fit_code("return to semicolon", "", "", ["to"]).text, "return to;")

    def test_brackets_said_unclearly(self):
        self.assertEqual(scoped("helper value open racket line count clothes bracket semicolon"),
                         "helper_value(lineCount);")
        self.assertEqual(scoped("return total semi colin"), "return total;")
        self.assertEqual(loose_symbol("open", "brase"), "{")
        self.assertIsNone(loose_symbol("total", "bracket"))
        self.assertIsNone(loose_symbol("open", "window"))

    def test_helpers(self):
        self.assertEqual(sound("sighs"), sound("size"))
        self.assertGreater(alike("pointer", "ptr"), 0.86)
        self.assertLess(alike("total", "count"), 0.5)
        self.assertEqual(snap(["line", "counts"], ["lineCount", "total"]), "lineCount")
        self.assertIsNone(snap(["banana"], ["lineCount", "total"]))
        self.assertEqual(position([], "    "), "start")
        self.assertEqual(position([], "x = "), "value")
        self.assertEqual(position([("op", ";")], ""), "start")
        self.assertEqual(position([("id", "x")], ""), "")
        self.assertTrue(declaring([("id", "int")], ""))
        self.assertTrue(declaring([], "    char *"))
        self.assertFalse(declaring([("id", "x"), ("op", "=")], ""))

    def test_prompt_puts_names_in_scope_first(self):
        said = prompt(["zebra"], {"lineCount": "variable", "char": "keyword"})
        self.assertTrue(said.endswith("line count zebra"))


class Context(unittest.TestCase):
    def test_joining_what_is_already_there(self):
        self.assertEqual(code("semicolon", before="int x = 5 "), "int x = 5;")
        self.assertEqual(code("equals five", before="int x"), "int x = 5")
        self.assertEqual(code("open bracket", before="printf"), "printf(")
        self.assertEqual(code("open bracket", before="if"), "if (")
        self.assertEqual(code("x", before="foo("), "foo(x")
        self.assertEqual(code("count", before="    "), "    count")
        self.assertEqual(code("close brace", before="    "), "    }")  # the editor steps it back
        self.assertEqual(code("x equals", after="y;"), "x = y;")
        self.assertEqual(code("stdio dot h close angle", before="#include <"), "#include <stdio.h>")
        self.assertEqual(code("minus one", before="x = "), "x = -1")
        self.assertEqual(code("minus one", before="x = y "), "x = y - 1")

    def test_a_line_break_before_existing_code_adds_no_space(self):
        self.assertEqual(code("x plus plus semicolon new line", before="    ", after="return x;"),
                         "    x++;" + LINE + "return x;")

    def test_angle_brackets_closed_in_a_later_phrase(self):
        self.assertEqual(code("close angle", before="#include <stdio.h"), "#include <stdio.h>")
        self.assertEqual(code("dot h close angle", before="#include <stdio"), "#include <stdio.h>")
        self.assertEqual(code("stdio dot h", before="#include <"), "#include <stdio.h")
        self.assertEqual(code("int close angle values", before="std::vector<"), "std::vector<int> values")
        self.assertEqual(code("b", before="if (a < "), "if (a < b")

    def test_backslash_n_however_it_is_heard(self):
        for heard in ("int", "in", "and", "ent", "hen", "n", "on"):
            self.assertEqual(
                code(f"backslash {heard} quote close bracket semicolon", before='printf("number = %d'),
                'printf("number = %d\\n");', heard)
        self.assertEqual(code("print f open bracket quote number equals percent d backslash int quote close bracket semicolon"),
                         'printf("number = %d\\n");')
        self.assertEqual(code("say space backslash quote hi backslash quote quote", before='puts("'),
                         'puts("say \\"hi\\""')

    def test_a_format_letter_after_percent(self):
        before, after = 'printf("the number is = %', '\\n", i);'
        for heard in ("D.", "d", "dee", "Dee."):
            self.assertEqual(code(heard, before=before, after=after),
                             'printf("the number is = %d\\n", i);', heard)
        self.assertEqual(code("percent d", before='printf("n = '), 'printf("n = %d')
        self.assertEqual(code("see", before="x = "), "x = c")
        self.assertEqual(code("see", before="x = ", names=["see"]), "x = see")

    def test_inside_a_string(self):
        self.assertEqual(code("hello there world", before='printf("'), 'printf("hello there world')
        self.assertEqual(code("quote close bracket semicolon", before='printf("hi'), 'printf("hi");')

    def test_where(self):
        self.assertEqual(where("int x = 5; "), ("code", ""))
        self.assertEqual(where('printf("hello'), ("string", ""))
        self.assertEqual(where('printf("hello"); // say hi'), ("comment", "say hi"))
        self.assertEqual(where('x = "//not a comment";'), ("code", ""))
        self.assertEqual(where(" * part of a block comment"), ("comment", "part of a block comment"))
        self.assertEqual(where('char c = \'"\';'), ("code", ""))

    def test_tokens(self):
        self.assertEqual(tokens("Semi-colon, new line."), ["semi", "colon", "new", "line"])
        self.assertEqual(tokens("x = 3.14;"), ["x", "=", "3.14", ";"])
        self.assertEqual(tokens("stdio.h"), ["stdio", ".", "h"])
        self.assertEqual(tokens("1,000"), ["1000"])
        self.assertEqual(tokens("open brackets closeangle"), ["open", "bracket", "close", "angle"])
        self.assertEqual(code("for open brackets int i close brackets"), "for (int i)")


if __name__ == "__main__":
    unittest.main()
