#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import print_function

import datetime
import glob
import json
import logging
import os
import sys
import time
import unittest

from juriscraper.lib.date_utils import (fix_future_year_typo,
                                        is_first_month_in_quarter,
                                        make_date_range_tuples, parse_dates,
                                        quarter)
from juriscraper.lib.importer import build_module_list
from juriscraper.lib.judge_parsers import normalize_judge_names, \
    normalize_judge_string
from juriscraper.lib.string_utils import (CaseNameTweaker, clean_string,
                                          convert_date_string, fix_camel_case,
                                          force_unicode, harmonize,
                                          normalize_dashes,
                                          split_date_range_string, titlecase)
from juriscraper.lib.test_utils import warn_generated_compare_file, \
    warn_or_crash_slow_parser
from juriscraper.opinions.united_states.state import colo, mass, massappct, \
    nh, pa
from juriscraper.oral_args.united_states.federal_appellate import ca6
from juriscraper.pacer.docket_utils import normalize_party_types


class DateTest(unittest.TestCase):
    def test_various_date_extractions(self):
        test_pairs = (
            # Dates separated by semicolons and JUMP words
            ('February 5, 1980; March 14, 1980 and May 28, 1980.',
             [datetime.datetime(1980, 2, 5, 0, 0),
              datetime.datetime(1980, 3, 14, 0, 0),
              datetime.datetime(1980, 5, 28, 0, 0)]),
            # Misspelled month value.
            ('Febraury 17, 1945',
             [datetime.datetime(1945, 2, 17, 0, 0)]),
            ('Sepetmber 19 1924',
             [datetime.datetime(1924, 9, 19)]),
            # Using 'Term' as an indicator.
            ('November Term 2004.',
             [datetime.datetime(2004, 11, 1)]),
            (u'April 26, 1961.[†]',
             [datetime.datetime(1961, 4, 26)]),
        )
        for pair in test_pairs:
            dates = parse_dates(pair[0])
            self.assertEqual(dates, pair[1])

    def test_fix_future_year_typo(self):
        correct = str(datetime.date.today().year)
        transposed = correct[0] + correct[2] + correct[1] + correct[3]
        expectations = {
            '12/01/%s' % transposed: '12/01/%s' % correct,  # Here's the fix
            '12/01/%s' % correct: '12/01/%s' % correct,     # Should not change
            '12/01/2806': '12/01/2806',                     # Should not change
            '12/01/2886': '12/01/2886',                     # Should not change
        }
        for before, after in expectations.items():
            fixed_date = fix_future_year_typo(convert_date_string(before))
            self.assertEqual(fixed_date, convert_date_string(after))

    def test_date_range_creation(self):
        q_a = ({
            # Six days (though it looks like five)
            'q': {'start': datetime.date(2017, 1, 1),
                  'end': datetime.date(2017, 1, 5),
                  'gap': 7},
            'a': [(datetime.date(2017, 1, 1), datetime.date(2017, 1, 5))],
        }, {
            # Seven days (though it looks like six)
            'q': {'start': datetime.date(2017, 1, 1),
                  'end': datetime.date(2017, 1, 6),
                  'gap': 7},
            'a': [(datetime.date(2017, 1, 1), datetime.date(2017, 1, 6))],
        }, {
            # Eight days (though it looks like seven)
            'q': {'start': datetime.date(2017, 1, 1),
                  'end': datetime.date(2017, 1, 8),
                  'gap': 7},
            'a': [(datetime.date(2017, 1, 1), datetime.date(2017, 1, 7)),
                  (datetime.date(2017, 1, 8), datetime.date(2017, 1, 8))],
        }, {
            # Gap bigger than range
            'q': {'start': datetime.date(2017, 1, 1),
                  'end': datetime.date(2017, 1, 5),
                  'gap': 1000},
            'a': [(datetime.date(2017, 1, 1), datetime.date(2017, 1, 5))],
        }, {
            # Ends before starts
            'q': {'start': datetime.date(2017, 1, 5),
                  'end': datetime.date(2017, 1, 1),
                  'gap': 7},
            'a': [],
        })
        for test in q_a:
            result = make_date_range_tuples(**test['q'])
            self.assertEqual(result, test['a'])


class ScraperExampleTest(unittest.TestCase):
    def setUp(self):
        self.maxDiff = 1000
        # Disable logging
        logging.disable(logging.CRITICAL)

    def tearDown(self):
        # Re-enable logging
        logging.disable(logging.NOTSET)

    def test_scrape_all_example_files(self):
        """Finds all the $module_example* files and tests them with the sample
        scraper.
        """

        module_strings = build_module_list('juriscraper')
        num_scrapers = len([s for s in module_strings
                            if 'backscraper' not in s])
        max_len_mod_string = max(len(mod) for mod in module_strings
                                 if 'backscraper' not in mod) + 2
        num_example_files = 0
        num_warnings = 0
        cnt = CaseNameTweaker()
        json_compare_extension = '.compare.json'
        json_compare_files_generated = []
        for module_string in module_strings:
            package, module = module_string.rsplit('.', 1)
            mod = __import__("%s.%s" % (package, module),
                             globals(),
                             locals(),
                             [module])
            if 'backscraper' not in module_string:
                sys.stdout.write(
                    '  %s ' % module_string.ljust(max_len_mod_string)
                )
                sys.stdout.flush()
                # module_parts:
                # [0]  - "juriscraper"
                # [1]  - "opinions" or "oral_args"
                # ...  - rest of the path
                # [-1] - module name
                module_parts = module_string.split('.')
                example_path = os.path.join(
                    "tests", "examples", module_parts[1],
                    "united_states", module_parts[-1],
                )
                paths = [path for path in glob.glob('%s_example*' % example_path)
                         if not path.endswith(json_compare_extension)]
                self.assertTrue(
                    paths,
                    "No example file found for: %s! \n\nThe test looked in: "
                    "%s" % (
                        module_string.rsplit('.', 1)[1],
                        os.path.join(os.getcwd(), example_path),
                    ))
                num_example_files += len(paths)
                t1 = time.time()
                num_tests = len(paths)
                for path in paths:
                    # This loop allows multiple example files per module
                    if path.endswith('~'):
                        # Text editor backup: Not interesting.
                        continue
                    site = mod.Site(cnt=cnt)
                    site.url = path
                    # Forces a local GET
                    site.enable_test_mode()
                    site.parse()
                    # Now validate that the parsed result is as we expect
                    json_path = '%s%s' % (path.rsplit('.', 1)[0], json_compare_extension)
                    json_data = json.loads(site.to_json(), encoding='utf-8')
                    if os.path.isfile(json_path):
                        # Compare result with corresponding json file
                        example_file = path.rsplit('/', 1)[1]
                        compare_file = json_path.rsplit('/', 1)[1]
                        with open(json_path, 'r') as input_file:
                            fixture_json = json.load(input_file)
                            self.assertEqual(
                                len(fixture_json),
                                len(json_data),
                                msg="Fixture and scraped data have different "
                                    "lengths: expected %s and scraped %s (%s)" % (
                                    len(fixture_json),
                                    len(json_data),
                                    module_string
                                )
                            )
                            for i, item in enumerate(fixture_json):
                                self.assertEqual(
                                    fixture_json[i],
                                    json_data[i],
                                )

                    else:
                        # Generate corresponding json file if it doesn't
                        # already exist. This should only happen once
                        # when adding a new example html file.
                        warn_generated_compare_file(json_path)
                        json_compare_files_generated.append(json_path)
                        with open(json_path, 'w') as json_example:
                            json.dump(json_data, json_example, indent=2)
                t2 = time.time()
                duration = t2 - t1
                warning_msg = warn_or_crash_slow_parser(t2 - t1)
                if warning_msg:
                    num_warnings += 1

                print('(%s test(s) in %0.1f seconds)' %
                      (num_tests, duration))

        print("\n{num_scrapers} scrapers tested successfully against "
              "{num_example_files} example files, with {num_warnings} "
              "speed warnings.".format(
                  num_scrapers=num_scrapers,
                  num_example_files=num_example_files,
                  num_warnings=num_warnings,))
        if json_compare_files_generated:
            msg = 'Generated compare file(s) during test, please review before proceeding. ' \
                  'If the data looks good, run tests again, then be sure to include ' \
                  'the new compare file(s) in your commit: %s'
            self.fail(msg % ', '.join(json_compare_files_generated))
        if num_warnings:
            print("\nAt least one speed warning was triggered during the "
                   "tests. If this is due to a slow scraper you wrote, we "
                   "suggest attempting to speed it up, as it will be slow "
                   "both in production and while running tests. This is "
                   "currently a warning, but may raise a failure in the "
                   "future as performance requirements are tightened.")
        else:
            # Someday, this line of code will be run. That day is not today.
            print("\nNo speed warnings detected. That's great, keep up the " \
                  "good work!")


class JudgeParsingTest(unittest.TestCase):
    def test_title_name_splitter(self):
        pairs = [{
            'q': 'Magistrate Judge George T. Swartz',
            'a': ('George T. Swartz', 'mag'),
        },
            {
                'q': 'J. Frederick Motz',
                'a': ('Frederick Motz', 'jud'),
            },
            {
                'q': 'Honorable Susan W. Wright',
                'a': ('Susan W. Wright', 'jud'),
            },
        ]

        for pair in pairs:
            self.assertEqual(pair['a'], normalize_judge_string(pair['q']))

    def test_name_normalization(self):
        pairs = [{
            'q': 'Michael J Lissner',
            'a': 'Michael J. Lissner',
        }, {
            'q': 'Michael Lissner Jr',
            'a': 'Michael Lissner Jr.',
        }, {
            'q': 'J Michael Lissner',
            'a': 'Michael Lissner',
        }, {
            'q': 'J. Michael J Lissner Jr',
            'a': 'Michael J. Lissner Jr.',
        }, {
            'q': 'J. J. Lissner',
            'a': 'J. J. Lissner',
        }]
        for pair in pairs:
            self.assertEqual(pair['a'], normalize_judge_names(pair['q']))

    def test_party_type_normalization(self):
        pairs = [{
            'q': 'Defendant                                 (1)',
            'a': 'Defendant'
        }, {
            'q': 'Debtor 2',
            'a': 'Debtor',
        }, {
            'q': 'ThirdParty Defendant',
            'a': 'Third Party Defendant',
        }, {
            'q': 'ThirdParty Plaintiff',
            'a': 'Third Party Plaintiff',
        }, {
            'q': '3rd Pty Defendant',
            'a': 'Third Party Defendant',
        }, {
            'q': '3rd party defendant',
            'a': 'Third Party Defendant',
        }, {
            'q': 'Counter-defendant',
            'a': 'Counter Defendant',
        }, {
            'q': 'Counter-Claimaint',
            'a': 'Counter Claimaint',
        }, {
            'q': 'US Trustee',
            'a': 'U.S. Trustee',
        }, {
            'q': 'United States Trustee',
            'a': 'U.S. Trustee',
        }, {
            'q': 'U. S. Trustee',
            'a': 'U.S. Trustee',
        }, {
            'q': 'BUS BOY',
            'a': 'Bus Boy',
        }, {
            'q': 'JointAdmin Debtor',
            'a': 'Jointly Administered Debtor',
        }, {
            'q': 'Intervenor-Plaintiff',
            'a': 'Intervenor Plaintiff',
        }, {
            'q': 'Intervenor Dft',
            'a': 'Intervenor Defendant',
        }]
        for pair in pairs:
            print("Normalizing PACER type of '%s' to '%s'..." %
                  (pair['q'], pair['a']), end='')
            result = normalize_party_types(pair['q'])
            self.assertEqual(result, pair['a'])
            print('✓')


class StringUtilTest(unittest.TestCase):
    def test_make_short_name(self):
        test_pairs = [
            # In re and Matter of
            ('In re Lissner', 'In re Lissner'),
            ('Matter of Lissner', 'Matter of Lissner'),

            # Plaintiff is in bad word list
            ('State v. Lissner', 'Lissner'),
            ('People v. Lissner', 'Lissner'),
            ('California v. Lissner', 'Lissner'),
            ('Dallas v. Lissner', 'Lissner'),

            # Basic 3-word case
            ('Langley v. Google', 'Langley'),
            # Similar to above, but more than 3 words
            ('Langley v. Google foo', 'Langley'),

            # United States v. ...
            ('United States v. Lissner', 'Lissner'),

            # Corporate first name
            ('Google, Inc. v. Langley', 'Langley'),
            ('Special, LLC v. Langley', 'Langley'),
            ('Google Corp. v. Langley', 'Langley'),

            # Shorter appellant than plaintiff
            ('Michael Lissner v. Langley', 'Langley'),

            # Multi-v with and w/o a bad_word
            ('Alameda v. Victor v. Keyboard', ''),
            ('Bloggers v. Victor v. Keyboard', ''),

            # Long left, short right
            ('Many words here v. Langley', 'Langley'),

            # Other manually added items
            ('Ilarion v. State', 'Ilarion'),
            ('Imery v. Vangil Ingenieros', 'Imery'),

            # Many more tests from real data!
            ('Bean v. City of Monahans', 'Bean'),
            ('Blanke v. Time, Inc.', 'Blanke'),
            ('New York Life Ins. Co. v. Deshotel', 'Deshotel'),
            ('Deatherage v. Deatherage', 'Deatherage'),
            ('Gonzalez Vargas v. Holder', ''),
            ('Campbell v. Wainwright', 'Campbell'),
            ('Liggett & Myers Tobacco Co. v. Finzer', 'Finzer'),
            ('United States v. Brenes', 'Brenes'),
            ('A.H. Robins Co., Inc. v. Eli Lilly & Co', ''),
            ('McKellar v. Hazen', 'McKellar'),
            ('Gil v. State', 'Gil'),
            ('Fuentes v. Owen', 'Fuentes'),
            ('State v. Shearer', 'Shearer'),
            ('United States v. Smither', 'Smither'),
            ('People v. Bradbury', 'Bradbury'),
            ('Venable (James) v. State', ''),
            ('Burkhardt v. Bailey', 'Burkhardt'),
            ('DeLorenzo v. Bales', 'DeLorenzo'),
            ('Loucks v. Bauman', 'Loucks'),
            ('Kenneth Stern v. Robert Weinstein', ''),
            ('Rayner v. Secretary of Health and Human Services', 'Rayner'),
            ('Rhyne v. Martin', 'Rhyne'),
            ('State v. Wolverton', 'Wolverton'),
            ('State v. Flood', 'Flood'),
            ('Amason v. Natural Gas Pipeline Co.', 'Amason'),
            ('United States v. Bryant', 'Bryant'),
            ('WELLS FARGO BANK v. APACHE TRIBE OF OKLAHOMA', ''),
            ('Stewart v. Tupperware Corp.', 'Stewart'),
            ('Society of New York Hosp. v. ASSOCIATED HOSP. SERV. OF NY', ''),
            ('Stein v. State Tax Commission', 'Stein'),
            (
                'The Putnam Pit, Inc. Geoffrey Davidian v. City of Cookeville, Tennessee Jim Shipley',
                ''),
            ('People v. Armstrong', 'Armstrong'),
            ('Weeks v. Weeks', 'Weeks'),
            ('Smith v. Xerox Corp.', ''),
            ('In Interest of Ad', ''),
            ('People v. Forsyth', 'Forsyth'),
            ('State v. LeClair', 'LeClair'),
            ('Agristor Credit Corp. v. Unruh', 'Unruh'),
            ('United States v. Larry L. Stewart', ''),
            ('Starling v. United States', 'Starling'),
            ('United States v. Pablo Colin-Molina', ''),
            ('Kenneth N. Juhl v. The United States', ''),
            ('Matter of Wilson', 'Matter of Wilson'),
            ('In Re Damon H.', ''),
            ('Centennial Ins. Co. v. Zylberberg', 'Zylberberg'),
            ('United States v. Donald Lee Stotler', ''),
            ('Byndloss v. State', 'Byndloss'),
            ('People v. Piatkowski', 'Piatkowski'),
            ('United States v. Willie James Morgan', ''),
            ('Harbison (Debra) v. Thieret (James)', ''),
            ('Federal Land Bank of Columbia v. Lieben', 'Lieben'),
            ('John Willard Greywind v. John T. Podrebarac', ''),
            ('State v. Powell', 'Powell'),
            ('Carr v. Galloway', 'Carr'),
            ('Saylors v. State', 'Saylors'),
            ('Jones v. Franke', 'Jones'),
            ('In Re Robert L. Mills, Debtor. Robert L. Mills v. Sdrawde '
             'Titleholders, Inc., a California Corporation', ''),
            ('Pollenex Corporation v. Sunbeam-Home Comfort, a Division of '
             'Sunbeam Corp., Raymond Industrial, Limited and Raymond Marketing '
             'Corporation of North America', ''),
            ('Longs v. State', 'Longs'),
            ('Performance Network Solutions v. Cyberklix', 'Cyberklix'),
            ('DiSabatino v. Salicete', 'DiSabatino'),
            ('State v. Jennifer Nicole Jackson', ''),
            ('United States v. Moreno', 'Moreno'),
            ('LOGAN & KANAWHA COAL v. Banque Francaise', ''),
            ('State v. Harrison', 'Harrison'),
            ('Efford v. Milam', 'Efford'),
            ('People v. Thompson', 'Thompson'),
            ('CINCINNATI THERMAL SPRAY v. Pender County', ''),
            ('JAH Ex Rel. RMH v. Wadle & Associates', ''),
            ('United Pub. Employees v. CITY & CTY. OF SAN FRAN.', ''),
            ('Warren v. Massachusetts Indemnity', 'Warren'),
            ('Marion Edwards v. State Farm Insurance Company and "John Doe,"',
             ''),
            ('Snowdon v. Grillo', 'Snowdon'),
            ('Adam Lunsford v. Cravens Funeral Home', ''),
            ('State v. Dillon', 'Dillon'),
            ('In Re Graham', 'In Re Graham'),
            ('Durham v. Chrysler Corp.', ''),  # Fails b/c Durham is a city!
            ('Carolyn Warrick v. Motiva Enterprises, L.L.C', ''),
            ('United States v. Aloi', 'Aloi'),
            ('United States Fidelity & Guaranty v. Graham', 'Graham'),
            ('Wildberger v. Rosenbaum', 'Wildberger'),
            ('Truck Insurance Exchange v. Michling', 'Michling'),
            ('Black Voters v. John J. McDonough', ''),
            ('State of Tennessee v. William F. Cain', ''),
            ('Robert J. Imbrogno v. Defense Logistics Agency', ''),
            ('Leetta Beachum, Administratrix v. Timothy Joseph White', ''),
            ('United States v. Jorge Gonzalez-Villegas', ''),
            ('Pitts v. Florida Bd. of Bar Examiners', 'Pitts'),
            ('State v. Pastushin', 'Pastushin'),
            ('Clark v. Clark', ''),
            ('Barrios v. Holder', 'Barrios'),
            ('Gregory L. Lavin v. United States', ''),
            ('Carpenter v. Consumers Power', 'Carpenter'),
            ('Derbabian v. S & C SNOWPLOWING, INC.', 'Derbabian'),
            ('Bright v. LSI CORP.', 'Bright'),
            ('State v. Brown', 'Brown'),
            ('KENNEY v. Keebler Co.', 'KENNEY'),
            ('Hill v. Chalanor', 'Hill'),
            ('Washington v. New Jersey', ''),
            ('Sollek v. Laseter', 'Sollek'),
            ('United States v. John Handy Jones, International Fidelity '
             'Insurance Company', ''),
            ('N.L.R.B. v. I. W. Corp', ''),
            ('Karpisek v. Cather & Sons Construction, Inc.', 'Karpisek'),
            ('Com. v. Wade', 'Com.'),
            ('Glascock v. Sukumlyn', 'Glascock'),
            ('Burroughs v. Hills', 'Burroughs'),
            ('State v. Darren Matthew Lee', ''),
            ('Mastondrea v. Occidental Hotels Management', 'Mastondrea'),
            ('Kent v. C. I. R', 'Kent'),
            ('Johnson v. City of Detroit', ''),
            ('Nolan v. United States', 'Nolan'),
            ('Currence v. Denver Tramway Corporation', 'Currence'),
            ('Matter of Cano', 'Matter of Cano'),
            # Two words after "Matter of --> Punt."
            ('Matter of Alphabet Soup', ''),
            # Zero words after "Matter of" --> Punt.
            ("Matter of", "Matter of"),
            ('Simmons v. Stalder', 'Simmons'),
            ('United States v. Donnell Hagood', ''),
            ('Kale v. United States INS', 'Kale'),
            ('Cmk v. Department of Revenue Ex Rel. Kb', 'Cmk'),
            ('State Farm Mut. Auto. Ins. Co. v. Barnes', 'Barnes'),
            ('In Re Krp', 'In Re Krp'),
            ('CH v. Department of Children and Families', 'CH'),
            ('Com. v. Monosky', 'Com.'),
            ('JITNEY-JUNGLE, INCORPORATED v. City of Brookhaven', ''),
            ('Carolyn Humphrey v. Memorial Hospitals Association', ''),
            ('Wagner v. Sanders Associates, Inc.', 'Wagner'),
            ('United States v. Venie (Arthur G.)', ''),
            ('Mitchell v. State', ''),
            ('City of Biloxi, Miss. v. Giuffrida', 'Giuffrida'),
            ('Sexton v. St. Clair Federal Sav. Bank', 'Sexton'),
            ('United States v. Matthews', 'Matthews'),
            ('Freeman v. Freeman', 'Freeman'),
            ('Spencer v. Toussaint', 'Spencer'),
            ('In Re Canaday', 'In Re Canaday'),
            ('Wenger v. Commission on Judicial Performance', 'Wenger'),
            ('Jackson v. Janecka', 'Janecka'),
            ('People of Michigan v. Ryan Christopher Smith', ''),
            ('Kincade (Michael) v. State', ''),
            ('Tonubbee v. River Parishes Guide', 'Tonubbee'),
            ('United States v. Richiez', 'Richiez'),
            ('In Re Allamaras', 'In Re Allamaras'),
            ('United States v. Capoccia', 'Capoccia'),
            ('Com. v. DeFranco', 'Com.'),
            ('Matheny v. Porter', 'Matheny'),
            ('Piper v. Hoffman', 'Piper'),
            ('People v. Smith', ''),  # Punted b/c People and Smith are bad.
            ('Mobuary, Joseph v. State.', ''),  # Punted b/c "State." has punct
        ]
        tweaker = CaseNameTweaker()
        for t in test_pairs:
            output = tweaker.make_case_name_short(t[0])
            self.assertEqual(output, t[1],
                             "Input was:\n\t%s\n\n\tExpected: '%s'\n\tActual: '%s'" %
                             (t[0], t[1], output))

    def test_quarter(self):
        answers = {1: 1, 2: 1, 3: 1, 4: 2, 5: 2, 6: 2, 7: 3, 8: 3, 9: 3, 10: 4,
                   11: 4, 12: 4}
        for month, q in answers.items():
            self.assertEqual(quarter(month), q)

    def test_is_first_month_in_quarter(self):
        answers = {
            1: True,
            2: False,
            3: False,
            4: True,
            5: False,
            6: False,
            7: True,
        }
        for month, is_first in answers.items():
            self.assertEqual(is_first_month_in_quarter(month), is_first)

    def test_harmonize_and_clean_string_tests(self):
        """Tests various inputs for the clean_string and harmonize functions"""
        test_pairs = [
            # Et al
            ['Lissner, et. al.',
             u'Lissner'],
            ['Lissner, et. al',
             u'Lissner'],
            ['Lissner, et al.',
             u'Lissner'],
            ['Lissner, et al',
             u'Lissner'],
            ['Lissner et. al.',
             u'Lissner'],
            ['Lissner et. al',
             u'Lissner'],
            ['Lissner et al.',
             u'Lissner'],
            ['Lissner et al',
             u'Lissner'],

            # US --> United States
            ['US v. Lissner, Plaintiff',
             u'United States v. Lissner'],
            ['US v. Lissner, Petitioner-appellant',
             u'United States v. Lissner'],
            ['United States, Petitioner, v. Lissner',
             u'United States v. Lissner'],
            [
                'United States of America, Plaintiff-Appellee, v. Orlando B. '
                'Pino, Defendant-Appellant, Joseph',
                u'United States v. Orlando B. Pino, Joseph'],
            ['Herring v. U.S. **',
             u'Herring v. United States'],
            ['Test v. U.S',
             u'Test v. United States'],
            ['The United States v. Lissner',
             u'United States v. Lissner'],
            # Tests the output from a titlecased word containing
            # US to ensure it gets harmonized.
            ['Carver v. US',
             u'Carver v. United States'],
            # US Steel --> US Steel
            ['US Steel v.  US',
             u'US Steel v. United States'],
            ['US v. V.Vivack',
             u'United States v. V.Vivack'],
            ['US vs. Lissner',
             u'United States v. Lissner'],
            ['vs.boxer@gmail.com vs. USA',
             u'vs.boxer@gmail.com v. United States'],
            ['US v. US',
             u'United States v. United States'],
            ['US  Steel v.  US',
             u'US Steel v. United States'],
            ['U.S.A. v. Mr. v.',
             u'United States v. Mr. v.'],
            ['U.S.S. v. Lissner',
             u'U.S.S. v. Lissner'],
            ['USC v. Lissner',
             u'USC v. Lissner'],
            ['U.S.C. v. Lissner',
             u'U.S.C. v. Lissner'],
            ['U.S. Steel v. Colgate',
             u'U.S. Steel v. Colgate'],
            ['U.S.A. v. Lissner',
             u'United States v. Lissner'],
            ['U.S. v. Lissner',
             u'United States v. Lissner'],
            ['U. S. v. Lissner',
             u'United States v. Lissner'],
            ['United States v. Lissner',
             u'United States v. Lissner'],
            ['Usa v. Lissner',
             u'United States v. Lissner'],
            ['USA v. Lissner',
             u'United States v. Lissner'],
            ['United States of America v. Lissner',
             u'United States v. Lissner'],
            ['Lissner v. United States of America',
             u'Lissner v. United States'],

            # tests no period in v.
            ['USA v White',
             u'United States v. White'],
            # tests no period in vs.
            ['USA vs White',
             u'United States v. White'],
            ['V.Vivack and Associates v. US',
             u'V.Vivack and Associates v. United States'],
            ['v.v. Hendricks & Sons v. James v. Smith',
             u'v.v. Hendricks & Sons v. James v. Smith'],

            # Normalize "The State"
            ['Aimee v. The State',
             u'Aimee v. State'],

            # Nuke Pet (short for petitioners)
            ['Commonwealth v. Mickle, V., Pet.',
             u'Commonwealth v. Mickle v.'],
            # Unchanged, despite having the word Pet
            ['Pet Doctors inc. v. Spoon',
             u'Pet Doctors inc. v. Spoon'],

            # Nukes the No. and Nos., but not
            ['No. 23423',
             u'23423'],
            ['Nos. 23 and 232',
             u'23 and 232'],
            ['No Expletives Inc.',
             u'No Expletives Inc.'],
            # Tests that "Nothing" doesn't get nuked.
            ['No. 232 Nothing 232',
             '232 Nothing 232'],

            # Garbage
            # leading slash.
            ['/USA vs White',
             u'United States v. White'],
            # unicode input
            ['12–1438-cr',
             u'12–1438-cr'],

            # Randoms
            ['clarinet alibi',
             u'clarinet alibi'],
            ['papusa',
             u'papusa'],
            ['CUSANO',
             u'CUSANO'],

            # Filter out invalid XML characters
            [u'Special Counsel ex rel. Karla Saunders',
             u'Special Counsel ex rel. Karla Saunders'],
        ]
        for pair in test_pairs:
            self.assertEqual(harmonize(clean_string(pair[0])), pair[1])

    def test_titlecase(self):
        """Tests various inputs for the titlecase function"""
        test_pairs = [
            ["Q&A with steve jobs: 'that's what happens in technology'",
             u"Q&A With Steve Jobs: 'That's What Happens in Technology'"],
            ["What is AT&T's problem?",
             u"What is AT&T's Problem?"],
            ['Apple deal with AT&T falls through',
             u'Apple Deal With AT&T Falls Through'],
            ['this v that',
             u'This v That'],
            ['this v. that',
             u'This v. That'],
            ['this vs that',
             u'This vs That'],
            ['this vs. that',
             u'This vs. That'],
            ["The SEC's Apple Probe: What You Need to Know",
             u"The SEC's Apple Probe: What You Need to Know"],
            ["'by the Way, small word at the start but within quotes.'",
             u"'By the Way, Small Word at the Start but Within Quotes.'"],
            ['Small word at end is nothing to be afraid of',
             u'Small Word at End is Nothing to Be Afraid Of'],
            ['Starting Sub-Phrase With a Small Word: a Trick, Perhaps?',
             u'Starting Sub-Phrase With a Small Word: A Trick, Perhaps?'],
            ["Sub-Phrase With a Small Word in Quotes: 'a Trick, Perhaps?'",
             u"Sub-Phrase With a Small Word in Quotes: 'A Trick, Perhaps?'"],
            ['Sub-Phrase With a Small Word in Quotes: "a Trick, Perhaps?"',
             u'Sub-Phrase With a Small Word in Quotes: "A Trick, Perhaps?"'],
            ['"Nothing to Be Afraid of?"',
             u'"Nothing to Be Afraid Of?"'],
            ['"Nothing to be Afraid Of?"',
             u'"Nothing to Be Afraid Of?"'],
            ['a thing',
             u'A Thing'],
            ["2lmc Spool: 'gruber on OmniFocus and vapo(u)rware'",
             u"2lmc Spool: 'Gruber on OmniFocus and Vapo(u)rware'"],
            ['this is just an example.com',
             u'This is Just an example.com'],
            ['this is something listed on del.icio.us',
             u'This is Something Listed on del.icio.us'],
            ['iTunes should be unmolested',
             u'iTunes Should Be Unmolested'],
            ['Reading between the lines of steve jobs’s ‘thoughts on music’',
             # Tests unicode
             u'Reading Between the Lines of Steve Jobs’s ‘Thoughts on Music’'],
            ['seriously, ‘repair permissions’ is voodoo',  # Tests unicode
             u'Seriously, ‘Repair Permissions’ is Voodoo'],
            [
                'generalissimo francisco franco: still dead; kieren McCarthy: '
                'still a jackass',
                u'Generalissimo Francisco Franco: Still Dead; Kieren McCarthy:'
                u' Still a Jackass'],
            ['Chapman v. u.s. Postal Service',
             u'Chapman v. U.S. Postal Service'],
            ['Spread Spectrum Screening Llc. v. Eastman Kodak Co.',
             u'Spread Spectrum Screening LLC. v. Eastman Kodak Co.'],
            [
                'Consolidated Edison Co. of New York, Inc. v. Entergy Nuclear '
                'Indian Point 2, Llc.',
                u'Consolidated Edison Co. of New York, Inc. v. Entergy Nuclear'
                u' Indian Point 2, LLC.'],
            ['Infosint s.a. v. H. Lundbeck A/s',
             u'Infosint S.A. v. H. Lundbeck A/S'],
            ["KEVIN O'CONNELL v. KELLY HARRINGTON",
             u"Kevin O'Connell v. Kelly Harrington"],
            ['International Union of Painter v. J&r Flooring, Inc',
             u'International Union of Painter v. J&R Flooring, Inc'],
            [
                'DOROTHY L. BIERY, and JERRAMY and ERIN PANKRATZ v. THE UNITED'
                ' STATES 07-693L And',
                u'Dorothy L. Biery, and Jerramy and Erin Pankratz v. the '
                u'United States 07-693l And'],
            ['CARVER v. US',
             u'Carver v. US']]

        for pair in test_pairs:
            unicode_string = force_unicode(pair[0])
            self.assertEqual(titlecase(unicode_string, DEBUG=False), pair[1])

    def test_fixing_camel_case(self):
        """Can we correctly identify and fix camelCase?"""
        test_pairs = (
            # A nasty one with a v in the middle and two uppercase letters
            ('Metropolitanv.PAPublic',
             'Metropolitan v. PA Public'),
            # An OK string.
            (
                'In Re Avandia Marketing Sales Practices & Products Liability '
                'Litigation',
                'In Re Avandia Marketing Sales Practices & Products Liability '
                'Litigation'),
            # Partial camelCase should be untouched.
            ('PPL EnergyPlus, LLC, et al v. Solomon, et al',
             'PPL EnergyPlus, LLC, et al v. Solomon, et al'),
            # The v. has issues.
            ('Pagliaccettiv.Kerestes',
             'Pagliaccetti v. Kerestes'),
            ('Coxv.Hornetal',
             'Cox v. Horn'),
            ('InReNortelNetworksInc',
             'In Re Nortel Networks Inc'),
            # Testing with a Mc.
            ('McLaughlinv.Hallinan',
             'McLaughlin v. Hallinan'),
            # Ends with uppercase letter
            ('TourchinvAttyGenUSA',
             'Tourchin v. Atty Gen USA'),
            ('USAv.Brown',
             'USA v. Brown'),
            # Fix 'of', ',etal', 'the', and 'Inre' problems
            ('RawdinvTheAmericanBrdofPediatrics',
             'Rawdin v. The American Brd of Pediatrics'),
            ('Santomenno,etalv.JohnHancockLifeInsuranceCompany,etal',
             'Santomenno v. John Hancock Life Insurance Company'),
            ('BaughvSecretaryoftheNavy',
             'Baugh v. Secretary of the Navy'),
            ('Smallv.CamdenCountyetal',
             'Small v. Camden County'),
            ('InreSCHCorpv.CFIClass',
             'In Re SCH Corp v. CFI Class'),
        )
        for pair in test_pairs:
            self.assertEqual(pair[1], fix_camel_case(pair[0]))

    def test_split_date_range_string(self):
        tests = {
            'October - December 2016': convert_date_string('November 16, 2016'),
            'July - September 2016': convert_date_string('August 16, 2016'),
            'April - June 2016': convert_date_string('May 16, 2016'),
            'January March 2016': False,
        }
        for before, after in tests.items():
            if after:
                self.assertEqual(split_date_range_string(before), after)
            else:
                with self.assertRaises(Exception):
                    split_date_range_string(before)

    def test_normalize_dashes(self):
        tests = [
            # copied from http://www.w3schools.com/charsets/ref_utf_punctuation.asp
            u' this is    –a test–',  # en dash
            u' this is    —a test—',  # em dash
            u' this is    ‐a test‐',  # hyphen
            u' this is    ‑a test‑',  # non-breaking hyphen
            u' this is    ‒a test‒',  # figure dash
            u' this is    ―a test―',  # horizontal bar
        ]
        target = ' this is    -a test-'
        for test in tests:
            self.assertEqual(normalize_dashes(test), target)


class ScraperSpotTest(unittest.TestCase):
    """Adds specific tests to specific courts that are more-easily tested
    without a full integration test.
    """

    def test_mass(self):
        strings = {
            'Massachusetts State Automobile Dealers Association, Inc. v. Tesla Motors MA, Inc. (SJC 11545) (September 15, 2014)': [
                'Massachusetts State Automobile Dealers Association, Inc. v. Tesla Motors MA, Inc.',
                'SJC 11545',
            ],
            'Bower v. Bournay-Bower (SJC 11478) (September 15, 2014)': [
                'Bower v. Bournay-Bower',
                'SJC 11478',
            ],
            'Commonwealth v. Holmes (SJC 11557) (September 12, 2014)': [
                'Commonwealth v. Holmes',
                'SJC 11557',
            ],
            'Superintendent-Director of Assabet Valley Regional School District v. Speicher (SJC 11563) (September 11, 2014)': [
                'Superintendent-Director of Assabet Valley Regional School District v. Speicher',
                'SJC 11563',
            ],
            'Commonwealth v. Quinn (SJC 11554) (September 11, 2014)': [
                'Commonwealth v. Quinn',
                'SJC 11554',
            ],
            'Commonwealth v. Wall (SJC 09850) (September 11, 2014)': [
                'Commonwealth v. Wall',
                'SJC 09850',
            ],
            'Commonwealth v. Letkowski (SJC 11556) (September 9, 2014)': [
                'Commonwealth v. Letkowski',
                'SJC 11556',
            ],
            'Commonwealth v. Sullivan (SJC 11568) (September 9, 2014)': [
                'Commonwealth v. Sullivan',
                'SJC 11568',
            ],
            'Plumb v. Casey (SJC 11519) (September 8, 2014)': [
                'Plumb v. Casey',
                'SJC 11519',
            ],
            'A.J. Properties, LLC v. Stanley Black and Decker, Inc. (SJC 11424) (September 5, 2014)': [
                'A.J. Properties, LLC v. Stanley Black and Decker, Inc.',
                'SJC 11424',
            ],
            'Massachusetts Electric Co. v. Department of Public Utilities (SJC 11526, 11527, 11528) (September 4, 2014)': [
                'Massachusetts Electric Co. v. Department of Public Utilities',
                'SJC 11526, 11527, 11528',
            ],
            'Commonwealth v. Doe (SJC-11861) (October 22, 2015)': [
                'Commonwealth v. Doe',
                'SJC-11861',
            ],
            'Commonwealth v. Teixeira; Commonwealth v. Meade (SJC 11929; SJC 11944) (September 16, 2016)': [
                'Commonwealth v. Teixeira; Commonwealth v. Meade',
                'SJC 11929; SJC 11944',
            ]
        }
        self.validate_mass_string_parse(strings, 'mass')

    def test_massappct(self):
        strings = {
            'Commonwealth v. Forbes (AC 13-P-730) (August 26, 2014)': [
                'Commonwealth v. Forbes',
                'AC 13-P-730',
            ],
            'Commonwealth v. Malick (AC 09-P-1292, 11-P-0973) (August 25, 2014)': [
                'Commonwealth v. Malick',
                'AC 09-P-1292, 11-P-0973',
            ],
            'Litchfield\'s Case (AC 13-P-1044) (August 28, 2014)': [
                'Litchfield\'s Case',
                'AC 13-P-1044',
            ],
            'Rose v. Highway Equipment Company (AC 13-P-1215) (August 27, 2014)': [
                'Rose v. Highway Equipment Company',
                'AC 13-P-1215',
            ],
            'Commonwealth v. Alves (AC 13-P-1183) (August 27, 2014)': [
                'Commonwealth v. Alves',
                'AC 13-P-1183',
            ],
            'Commonwealth v. Dale (AC 12-P-1909) (August 25, 2014)': [
                'Commonwealth v. Dale',
                'AC 12-P-1909',
            ],
            'Kewley v. Department of Elementary and Secondary Education (AC 13-P-0833) (August 22, 2014)': [
                'Kewley v. Department of Elementary and Secondary Education',
                'AC 13-P-0833',
            ],
            'Hazel\'s Cup & Saucer, LLC v. Around The Globe Travel, Inc. (AC 13-P-1371) (August 22, 2014)': [
                'Hazel\'s Cup & Saucer, LLC v. Around The Globe Travel, Inc.',
                'AC 13-P-1371',
            ],
            'Becker v. Phelps (AC 13-P-0951) (August 22, 2014)': [
                'Becker v. Phelps',
                'AC 13-P-0951',
            ],
            'Barrow v. Dartmouth House Nursing Home, Inc. (AC 13-P-1375) (August 18, 2014)': [
                'Barrow v. Dartmouth House Nursing Home, Inc.',
                'AC 13-P-1375',
            ],
            'Zimmerling v. Affinity Financial Corp. (AC 13-P-1439) (August 18, 2014)': [
                'Zimmerling v. Affinity Financial Corp.',
                'AC 13-P-1439',
            ],
            'Lowell v. Talcott (AC 13-P-1053) (August 18, 2014)': [
                'Lowell v. Talcott',
                'AC 13-P-1053',
            ],
            'Copley Place Associates, LLC v. Tellez-Bortoni (AC 16-P-165) (January 01, 2017)': [
                'Copley Place Associates, LLC v. Tellez-Bortoni',
                'AC 16-P-165',
            ],
        }
        self.validate_mass_string_parse(strings, 'massappct')

    def validate_mass_string_parse(self, strings, site_id):
        """Non-test method"""
        if site_id not in ['mass', 'massappct']:
            self.fail("You provided an invalid site string to validate_mass_string_parse: %s" % site_id)
        site = mass.Site() if site_id == 'mass' else massappct.Site()
        for raw_string, parsed in strings.items():
            # Set year on site scraper
            site.year = int(raw_string.split(' ')[-1].rstrip(')'))
            site.set_local_variables()
            try:
                # make sure name is parsed
                self.assertEqual(
                    site.grouping_regex.search(raw_string).group(1).strip(),
                    parsed[0],
                )
                # make sure docket is parsed
                self.assertEqual(
                    site.grouping_regex.search(raw_string).group(2).strip(),
                    parsed[1],
                )
            except AttributeError:
                self.fail("Unable to parse %s string: '%s'" % (site_id, raw_string))

    def test_nh(self):
        """Ensures regex parses what we think it should."""
        string_pairs = (
            ('2012-644, State of New Hampshire v. Adam Mueller',
             'State of New Hampshire v. Adam Mueller',),
            ('2012-920, In re Trevor G.',
             'In re Trevor G.',),
            ('2012-313, State of New Hampshire v. John A. Smith',
             'State of New Hampshire v. John A. Smith',),
            ('2012-729, Appeal of the Local Government Center, Inc. & a . ',
             'Appeal of the Local Government Center, Inc. & a .',),
            ('2013-0343  In the Matter of Susan Spenard and David Spenard',
             'In the Matter of Susan Spenard and David Spenard',),
            ('2013-0893, Stephen E. Forster d/b/a Forster’s Christmas Tree',
             'Stephen E. Forster d/b/a Forster’s Christmas Tree'),
        )
        regex = nh.Site().link_text_regex
        for test, result in string_pairs:
            try:
                case_name = regex.search(test).group(2).strip()
                self.assertEqual(
                    case_name,
                    result,
                    msg="Did not get expected results when regex'ing: '%s'.\n"
                        "  Expected: '%s'\n"
                        "  Instead:  '%s'" % (test, result, case_name)
                )
            except AttributeError:
                self.fail("Unable to parse nh string: '{s}'".format(s=test))

    def test_colo_coloctapp(self):
        """Ensures colo/coloctapp regex parses what we think it should."""
        tests = {
            '2016 COA 38. Nos. 14CA2454, 14CA2455, 14CA2456 & 14CA1457. People in the Interest of E.M.': {
                'docket': '14CA2454, 14CA2455, 14CA2456, 14CA1457',
                'name': 'People in the Interest of E.M',
            },
            '2016 COA 32. No. 14CA1424. Brooks, Jr. v. Raemisch.': {
                'docket': '14CA1424',
                'name': 'Brooks, Jr. v. Raemisch',
            },
            '2016 COA 33. Nos. 14CA1483 & 15CA0216. Rocky Mountain Exploration, Inc. v. Davis Graham & Stubbs LLP. ': {
                'docket': '14CA1483, 15CA0216',
                'name': 'Rocky Mountain Exploration, Inc. v. Davis Graham & Stubbs LLP',
            },
            '2016 COA 79. 14CA2487. People v. Fransua.': {
                'docket': '14CA2487',
                'name': 'People v. Fransua',
            },
            '2016 COA 51. No. 14CA2073.Campaign Integrity Watchdog v. Coloradans for a Better Future.': {
                'docket': '14CA2073',
                'name': 'Campaign Integrity Watchdog v. Coloradans for a Better Future',
            },
            '2016 CO 43. No. 14SC1. Martinez v. Mintz.': {
               'docket': '14SC1',
               'name': 'Martinez v. Mintz',
            },
            'No. 2016 COA 137. 15CA0620. Edwards v. Colorado Department of Revenue, Motor Vehicle Division. ': {
                'docket': '15CA0620',
                'name': 'Edwards v. Colorado Department of Revenue, Motor Vehicle Division',
            }
            #'': {
            #    'docket': '',
            #    'name': '',
            #},
        }

        scraper = colo.Site()
        for raw_string, data in tests.items():
            for field in ['docket', 'name']:
                attribute = '_extract_%s_from_text' % field
                result = getattr(scraper, attribute)(raw_string)
                self.assertEqual(
                    data[field],
                    result,
                    msg="Did not get expected %s results when regex'ing: '%s'.\n  Expected: '%s'\n  Instead:  '%s'" % (
                        field, raw_string, data[field], result
                    )
                )

    def test_ca6_oa(self):
        # Tests are triads. 1: Input s, 2: Group 1, 3: Group 2.
        tests = (
            ('13-4101 Avis Rent A Car V City of Dayton Ohio',
             '13-4101',
             'Avis Rent A Car V City of Dayton Ohio'),
            ('13-3950 13-3951 USA v Damien Russ',
             '13-3950 13-3951',
             'USA v Damien Russ'),
            ('09 5517  USA vs Taylor',
             '09 5517',
             'USA vs Taylor'),
            ('11-2451Spikes v Mackie',
             '11-2451',
             'Spikes v Mackie'),
        )
        regex = ca6.Site().regex
        for test, group_1, group_2 in tests:
            try:
                result_1 = regex.search(test).group(1).strip()
                self.assertEqual(
                    result_1,
                    group_1,
                    msg="Did not get expected results when regex'ing: '%s'.\n"
                        "  Expected: '%s'\n"
                        "  Instead:  '%s'" % (test, group_1, result_1)
                )
                result_2 = regex.search(test).group(2).strip()
                self.assertEqual(
                    result_2,
                    group_2,
                    msg="Did not get expected results when regex'ing: '%s'.\n"
                        "  Expected: '%s'\n"
                        "  Instead:  '%s'" % (test, group_2, result_2)
                )
            except AttributeError:
                self.fail("Unable to parse ca6 string: '{s}'".format(s=test))


if __name__ == '__main__':
    unittest.main()
