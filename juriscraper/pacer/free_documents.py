"""
The design here is intended to be used by Celery tasks, so the goal is to
make something that can be run in parallel by a huge number of tasks.

There are a few opportunities to split this up. The general process is as
below:

 + Log into the jurisdiction.
 + Query the free documents report (split this by date range).
 + Download each of the results in the report in its own task.

The only item above that can't be made parallel is logging in, but that's fine
because logging in is a one step thing.
"""
import re

import requests
from dateutil.rrule import rrule, DAILY
from lxml.html import tostring

from juriscraper.lib.html_utils import set_response_encoding, clean_html, \
    fix_links_in_lxml_tree, get_html_parsed_text
from juriscraper.lib.log_tools import make_default_logger
from juriscraper.lib.string_utils import convert_date_string
from juriscraper.pacer.utils import verify_court_ssl, \
    get_pacer_case_id_from_docket_url, get_pacer_document_number_from_doc1_url, \
    get_court_id_from_url

logger = make_default_logger()


def make_written_report_url(court_id):
    if court_id == 'ohnd':
        return 'https://ecf.ohnd.uscourts.gov/cgi-bin/OHND_WrtOpRpt.pl'
    else:
        return 'https://ecf.%s.uscourts.gov/cgi-bin/WrtOpRpt.pl' % court_id


def get_written_report_token(court_id, session):
    """Get the token that's part of the post form.

    This appears to be a kind of CSRF token. In the HTML of every page, there's
    a random token that's added to the form, like so:

        <form enctype="multipart/form-data" method="POST" action="../cgi-bin/WrtOpRpt.pl?196235599000508-L_1_0-1">

    This function simply loads the written report page, extracts the token and
    returns it.
    """
    url = make_written_report_url(court_id)
    logger.info("Getting written report CSRF token from %s" % url)
    r = session.get(
        url,
        headers={'User-Agent': 'Juriscraper'},
        verify=verify_court_ssl(court_id),
        timeout=450,
    )
    m = re.search('../cgi-bin/(?:OHND_)?WrtOpRpt.pl\?(.+)\"', r.text)
    if m is not None:
        return m.group(1)


def query_free_documents_report(court_id, start, end, cookie):
    if court_id in ['casb', 'innb', 'mieb', 'miwb', 'ohsb']:
        logger.error("Cannot get written opinions report from '%s'. It is "
                     "not provided by the court." % court_id)
        return []
    s = requests.session()
    s.cookies.set(**cookie)
    written_report_url = make_written_report_url(court_id)
    csrf_token = get_written_report_token(court_id, s)
    dates = [d.strftime('%m/%d/%Y') for d in rrule(DAILY, interval=1,
                                                   dtstart=start, until=end)]
    responses = []
    for d in dates:
        # Iterate one day at a time. Any more and PACER chokes.
        logger.info("Querying written opinions report for '%s' between %s and "
                    "%s" % (court_id, d, d))
        responses.append(s.post(
            written_report_url + '?' + csrf_token,
            headers={'User-Agent': 'Juriscraper'},
            verify=verify_court_ssl(court_id),
            timeout=300,
            files={
                'filed_from': ('', d),
                'filed_to': ('', d),
                'ShowFull': ('', '1'),
                'Key1': ('', 'cs_sort_case_numb'),
                'all_case_ids': ('', '0'),
            }
        ))
    return responses


class FreeOpinionRow(object):
    """A row in the Free Opinions report.

    For the most part this is fairly straightforward, however eight courts have
    a different type of report that only has four columns instead of the usual
    five (hib, deb, njb, ndb, ohnb, txsb, txwb, vaeb), and a couple courts
    (areb & arwb) have five columns, but are designed more like the four column
    variants.

    In general, what we do is detect the column count early on and then work
    from there.
    """
    def __init__(self, element, last_good_row, court_id):
        """Initialize the object.

        last_good_row should be a dict representing the values from the previous
        row in the table. This is necessary, because the report skips the case
        name if it's the same for two cases in a row. For example:

        Joe v. Volcano | 12/31/2008 | 128 | The first doc from case | More here
                       | 12/31/2008 | 129 | The 2nd doc from case   | More here

        By having the values from the previous row, we can be sure to be able
        to complete the empty cells.
        """
        super(FreeOpinionRow, self).__init__()
        self.element = element
        self.last_good_row = last_good_row
        self.court_id = court_id
        self.column_count = self.get_column_count()

        # Parsed data
        self.pacer_case_id = self.get_pacer_case_id()
        self.docket_number = self.get_docket_number()
        self.case_name = self.get_case_name()
        self.case_date = self.get_case_date()
        self.pacer_document_number = self.get_pacer_document_number()
        self.document_number = self.get_document_number()
        self.description = self.get_description()
        self.nature_of_suit = self.get_nos()
        self.cause = self.get_cause()

    def __str__(self):
        return '<FreeOpinionRow in %s>\n%s' % (self.court_id,
                                               tostring(self.element))

    def as_dict(self):
        """Similar to the __dict__ field, but excludes several fields."""
        attrs = {}
        for k, v in self.__dict__.items():
            if k not in ['element', 'last_good_row']:
                attrs[k] = v
        return attrs

    def get_column_count(self):
        return len(self.element.xpath('./td'))

    def get_pacer_case_id(self):
        try:
            docket_url = self.element.xpath('./td[1]//@href')[0]
        except IndexError:
            logger.info("No content provided in first cell of row. Using last "
                        "good row for pacer_case_id, docket_number, and "
                        "case_name.")
            return self.last_good_row['pacer_case_id']
        else:
            return get_pacer_case_id_from_docket_url(docket_url)

    def get_docket_number(self):
        try:
            s = self.element.xpath('./td[1]//a/text()')[0]
        except IndexError:
            return self.last_good_row['docket_number']
        else:
            if self.column_count == 4 or self.court_id in ['areb', 'arwb']:
                # In this case s will be something like: 14-90018 Stewart v.
                # Kauanui. split on the first space, left is docket number,
                # right is case name.
                return s.split(' ', 1)[0]
            else:
                return s

    def get_case_name(self):
        cell = self.element.xpath('./td[1]')[0]
        if self.column_count == 4 or self.court_id in ['areb', 'arwb']:
            # See note in docket number
            s = cell.text_content().strip()
            if s:
                return s.split(' ', 1)[1]
            else:
                return self.last_good_row['case_name']
        else:
            try:
                return cell.xpath('.//b')[0].text_content()
            except IndexError:
                return self.last_good_row['case_name']

    def get_case_date(self):
        return convert_date_string(self.element.xpath('./td[2]//text()')[0])

    def get_pacer_document_number(self):
        doc1_url = self.element.xpath('./td[3]//@href')[0]
        return get_pacer_document_number_from_doc1_url(doc1_url)

    def get_document_number(self):
        return self.element.xpath('./td[3]//text()')[0]

    def get_description(self):
        return self.element.xpath('./td[4]')[0].text_content()

    def get_nos(self):
        if self.column_count == 4:
            return None
        try:
            return self.element.xpath('./td[5]/i[contains(./text(), '
                                      '"NOS")]')[0].tail.strip()
        except IndexError:
            return None

    def get_cause(self):
        if self.column_count == 4:
            return None
        try:
            return self.element.xpath('./td[5]/i[contains(./text(), '
                                      '"Cause")]')[0].tail.strip()
        except IndexError:
            return None


def parse_written_opinions_report(responses):
    """Using a list of responses, parse out useful information and return it as
    a list of dicts.
    """
    results = []
    court_id = "Court not yet set."
    for response in responses:
        response.raise_for_status()
        court_id = get_court_id_from_url(response.url)
        set_response_encoding(response)
        text = clean_html(response.text)
        tree = get_html_parsed_text(text)
        tree.rewrite_links(fix_links_in_lxml_tree,
                           base_href=response.url)
        opinion_count = int(tree.xpath('//b[contains(text(), "Total number of '
                                       'opinions reported")]')[0].tail)
        if opinion_count == 0:
            continue
        rows = tree.xpath('(//table)[1]//tr[position() > 1]')
        for row in rows:
            if results:
                # If we have results already, pass the previous result to the
                # FreeOpinionRow object.
                row = FreeOpinionRow(row, results[-1], court_id)
            else:
                row = FreeOpinionRow(row, {}, court_id)
            results.append(row.as_dict())
    logger.info("Parsed %s results from %s" % (len(results), court_id))
    return results
