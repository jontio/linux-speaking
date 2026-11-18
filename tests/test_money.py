"""Sums of money are written one way: in figures."""
import unittest

from dictation import money
from dictation.money import in_figures, number


class InFigures(unittest.TestCase):
    def same(self, pairs):
        for said, want in pairs.items():
            self.assertEqual(in_figures(said), want, said)

    def test_a_sum_in_words_is_put_in_figures(self):
        self.same({
            "Today I spent a hundred and fifty dollars.": "Today I spent $150.",
            "Today I spent one hundred and twenty dollars on lunch.": "Today I spent $120 on lunch.",
            "We raised two thousand five hundred dollars.": "We raised $2,500.",
            "Fifteen hundred dollars is a lot.": "$1,500 is a lot.",
            "Three hundred and sixty five thousand dollars.": "$365,000.",
            "nine hundred ninety nine dollars": "$999",
            "Twenty-five dollars.": "$25.",
            "One dollar each.": "$1 each.",
        })

    def test_cents_go_after_the_point(self):
        self.same({
            "It cost twenty dollars and fifty cents.": "It cost $20.50.",
            "I have one hundred and one dollars and five cents.": "I have $101.05.",
        })

    def test_millions_keep_the_word(self):
        self.same({
            "It is worth one point five million dollars.": "It is worth $1.5 million.",
            "A million dollars would be nice.": "$1 million would be nice.",
            "two million three hundred thousand dollars": "$2.3 million",
            "one million two hundred thousand and fifty dollars": "$1,200,050",
        })

    def test_figures_the_recogniser_wrote_get_the_sign_too(self):
        self.same({
            "I paid 120 dollars.": "I paid $120.",
            "I paid 2,000 dollars.": "I paid $2,000.",
            "I paid $120 dollars.": "I paid $120.",
            "I spent $120 today.": "I spent $120 today.",
        })

    def test_one_or_the_other_and_from_one_to_the_other(self):
        self.same({
            "It costs twenty or thirty dollars.": "It costs $20 or $30.",
            "From twenty to thirty dollars each.": "From $20 to $30 each.",
            "Two or three hundred dollars.": "$200 or $300.",
            "Twenty or thirty thousand dollars.": "$20,000 or $30,000.",
            "One or two million dollars.": "$1 million or $2 million.",
            "Five hundred or six hundred dollars.": "$500 or $600.",
            "apples or twenty dollars": "apples or $20",
            "I want to pay twenty dollars.": "I want to pay $20.",
        })

    def test_two_or_three_hundred_written_in_figures(self):
        # Parakeet writes "two or three hundred Australian dollars" as "2 or 300 ...".
        self.same({"It cost 2 or 300 Australian dollars.": "It cost AU$200 or AU$300.",
                   "5 or 6,000 dollars": "$5,000 or $6,000", "50 to 60,000 dollars": "$50,000 to $60,000",
                   "12 or 1500 dollars": "$1,200 or $1,500", "two or 300 dollars": "$200 or $300",
                   # ... but not where the first is no smaller, or it isn't round
                   "20 or 30 dollars": "$20 or $30", "50 or 100 dollars": "$50 or $100",
                   "10 or 2000 dollars": "$10 or $2,000", "2 or 350 dollars": "$2 or $350",
                   "500 or 1,000,000 dollars": "$500 or $1 million"})

    def test_a_number_said_straight_after_a_money_sign_is_in_figures(self):
        # With the 5 of "$5" selected, "six" is said: the sign is still there before it.
        for said, before, want in (("six", "The price is $", "6"), ("Six.", "It cost $", "6."),
                                   ("a hundred and fifty", "AU$", "150"), ("twenty", "£", "20"),
                                   ("two thousand", "€", "2,000"), ("6", "$", "6"),
                                   # ... and nothing else is touched
                                   ("six", "The price is ", "six"), ("six of them", "$", "six of them"),
                                   ("a", "$", "a"), ("and", "$", "and"), ("", "$", "")):
            self.assertEqual(in_figures(said, before), want, (said, before))

    def test_whose_dollars(self):
        self.same({"A hundred NZ dollars.": "NZ$100.", "Fifty US dollars each.": "US$50 each.",
                   "Fifty to sixty NZ dollars.": "NZ$50 to NZ$60.",
                   "Ten Hong Kong dollars.": "HK$10.",
                   "It was $100 Australian dollars.": "It was AU$100."})

    def test_whose_dollars_are_never_one_letter(self):
        # "A$300" at the start of a phrase was typed "a$300": the lone "A" was taken for
        # the word. Two letters can't be.
        self.same({"Three hundred Australian dollars.": "AU$300.",
                   "one hundred Australian dollars": "AU$100",
                   "Fifty Canadian dollars.": "CA$50."})
        for sign in set(money._WHOSE.values()):
            self.assertRegex(sign, r"^[A-Z]{2}\$$")

    def test_pounds_that_are_said_to_be_money(self):
        self.same({"a hundred UK pounds": "£100", "A hundred British pounds.": "£100.",
                   "100 U.K. pounds": "£100", "one UK pound": "£1",
                   "twenty pounds sterling and fifty pence": "£20.50",
                   "two or three hundred UK pounds": "£200 or £300",
                   "It was £100 UK pounds.": "It was £100.", "I paid £100 pounds.": "I paid £100.",
                   "It cost £20 sterling.": "It cost £20.",          # as Parakeet writes it
                   "It cost £20 pounds sterling.": "It cost £20."})

    def test_pounds_that_may_be_a_weight_are_left(self):
        for said in ("It weighs a hundred pounds.", "I paid twenty pounds.", "a 380 pound gorilla",
                     "UK pounds are strong", "a hundred US pounds"):
            self.assertEqual(in_figures(said), said)

    def test_euros(self):
        self.same({"a hundred euros": "€100", "It cost 10 euros.": "It cost €10.",
                   "ten euros and fifty cents": "€10.50", "a twenty euro note": "a €20 note",
                   "twenty or thirty euros": "€20 or €30", "one point five million euros": "€1.5 million",
                   "I paid €10 euros.": "I paid €10."})

    def test_money_that_is_nobodys_is_left(self):
        for said in ("fifty British dollars", "ten Australian euros", "five dollars and ten pence",
                     "a few euros", "the dollars and the euros"):
            self.assertEqual(in_figures(said), said)
        self.same({"twenty UK pounds and five p.m.": "£20 and five p.m."})

    def test_a_note_of_so_many_dollars(self):
        self.same({"He gave me a twenty dollar note.": "He gave me a $20 note.",
                   "I found a hundred dollar bill.": "I found a hundred dollar bill."})   # the "a" is the bill's

    def test_what_is_not_a_whole_number_of_dollars_is_left(self):
        for said in ("It cost a few dollars.", "Millions of dollars were lost.", "It cost a dollar.",
                     "The dollars add up.", "Two and a half dollars.", "ten or twenty of the dollars",
                     "ten of the euros and twenty pounds", "A hundred and fifty people came.",
                     "Nothing about money here."):
            self.assertEqual(in_figures(said), said)

    def test_what_stands_before_the_number_is_kept(self):
        self.same({"Apples and twenty dollars.": "Apples and $20.",
                   "the twenty twenty dollars": "the twenty $20"})


class Numbers(unittest.TestCase):
    def test_words_to_a_number(self):
        for said, want in (("a hundred and fifty", 150), ("fifteen hundred", 1500), ("twenty one", 21),
                           ("two thousand five hundred", 2500), ("one point five million", 1500000),
                           ("a thousand", 1000), ("ninety nine", 99), ("120", 120), ("2,000", 2000),
                           ("1.5 million", 1500000)):
            self.assertEqual(number(said.split()), want, said)

    def test_what_is_no_number(self):
        for said in ("", "a", "and", "twenty thirty", "a twenty", "hundred", "two and", "and two",
                     "two thousand five thousand", "apples", "nineteen twenty"):
            self.assertIsNone(number(said.split()), said)


if __name__ == "__main__":
    unittest.main()
