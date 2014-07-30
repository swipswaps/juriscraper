# Scraper for the 3rd District Court of Appeals
#CourtID: ohioctapp3
#Court Short Name: Ohio
#Author: Andrei Chelaru
#Reviewer:
#Date: 2014-07-30

from juriscraper.opinions.united_states.state import ohio


class Site(ohio.Site):
    def __init__(self):
        super(Site, self).__init__()
        self.court_id = self.__module__
        self.court_index = 3