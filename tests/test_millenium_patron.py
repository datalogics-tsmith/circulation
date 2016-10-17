import pkgutil
from datetime import date, datetime, timedelta
from nose.tools import (
    eq_,
    set_trace,
)

from api.config import (
    Configuration,
    temp_config,
)

from api.authenticator import PatronData
from api.millenium_patron import MilleniumPatronAPI
from . import DatabaseTest, sample_data

class MockResponse(object):
    def __init__(self, content):
        self.status_code = 200
        self.content = content

class MockAPI(MilleniumPatronAPI):

    def __init__(self, root="", *args, **kwargs):
        super(MockAPI, self).__init__(root, *args, **kwargs)
        self.queue = []

    def sample_data(self, filename):
        return sample_data(filename, 'millenium_patron')

    def enqueue(self, filename):
        data = self.sample_data(filename)
        self.queue.append(data)

    def request(self, *args, **kwargs):
        return MockResponse(self.queue.pop())


class TestMilleniumPatronAPI(DatabaseTest):

    def setup(self):
        super(TestMilleniumPatronAPI, self).setup()
        self.api = MockAPI()

    def test_from_config(self):
        api = None
        with temp_config() as config:
            data = {
                Configuration.URL : "http://example.com",
                Configuration.AUTHORIZATION_IDENTIFIER_BLACKLIST : ["a", "b"]
            }
            config[Configuration.INTEGRATIONS] = {
                MilleniumPatronAPI.CONFIGURATION_NAME : data
            }
            api = MilleniumPatronAPI.from_config()
        eq_("http://example.com/", api.root)
        eq_(["a", "b"], api.authorization_identifier_blacklist)
            
    def test_remote_patron_lookup_no_such_patron(self):
        self.api.enqueue("dump.no such barcode.html")
        patrondata = PatronData(authorization_identifier="bad barcode")
        eq_(None, self.api.remote_patron_lookup(patrondata))

    def test_remote_patron_lookup_success(self):
        self.api.enqueue("dump.success.html")
        patrondata = PatronData(authorization_identifier="good barcode")
        patrondata = self.api.remote_patron_lookup(patrondata)

        # Although "good barcode" was successful in lookup this patron
        # up, it didn't show up in their patron dump as a barcode, so
        # the authorization_identifier from the patron dump took
        # precedence.
        eq_("6666666", patrondata.permanent_id)
        eq_("44444444444447", patrondata.authorization_identifier)
        eq_("alice", patrondata.username)

        # TODO: test fines, external_type, authorization_expires.
        
    def test_parse_poorly_behaved_dump(self):
        """The HTML parser is able to handle HTML embedded in
        field values.
        """
        self.api.enqueue("dump.embedded_html.html")
        patrondata = PatronData(authorization_identifier="good barcode")
        patrondata = self.api.remote_patron_lookup(patrondata)
        eq_("abcd", patrondata.authorization_identifier)

    def test_incoming_authorization_identifier_retained(self):
        # TODO: This should test patron_dump_to_patrondata, not
        # remote_patron_lookup.
        
        # This patron has two barcodes.
        self.api.enqueue("dump.two_barcodes.html")

        # Let's say they authenticate with the first one.
        patrondata = PatronData(authorization_identifier="FIRST_barcode")
        patrondata = self.api.remote_patron_lookup(patrondata)
        # Their Patron record will use their first barcode as authorization
        # identifier, because that's what they typed in.
        eq_("FIRST_barcode", patrondata.authorization_identifier)

        # Let's say they authenticate with the second barcode.
        self.api.enqueue("dump.two_barcodes.html")
        patrondata = PatronData(authorization_identifier="SECOND_barcode")
        patrondata = self.api.remote_patron_lookup(patrondata)
        # Their Patron record will use their second barcode as authorization
        # identifier, because that's what they typed in.
        eq_("SECOND_barcode", patrondata.authorization_identifier)

        # Let's say they authenticate with a barcode that immediately
        # stops working after they authenticate.
        self.api.enqueue("dump.two_barcodes.html")
        patrondata = PatronData(
            authorization_identifier="some other identifier"
        )
        patrondata = self.api.remote_patron_lookup(patrondata)
        # Their Patron record will use the second barcode as
        # authorization identifier, because it was probably added last.
        eq_("SECOND_barcode", patrondata.authorization_identifier)

        
    def test_remote_authenticate_no_such_barcode(self):
        self.api.enqueue("pintest.no such barcode.html")
        eq_(False, self.api.remote_authenticate("wrong barcode", "pin"))

    def test_remote_authenticate_wrong_pin(self):
        self.api.enqueue("pintest.bad.html")
        eq_(False, self.api.remote_authenticate("barcode", "wrong pin"))

    def test_remote_authenticate_correct_pin(self):
        self.api.enqueue("pintest.good.html")
        patrondata = self.api.remote_authenticate(
            "barcode1234567", "correct pin"
        )
        # The return value includes everything we know about the
        # authenticated patron, which isn't much.
        eq_("barcode1234567", patrondata.authorization_identifier)

    def test_update_patron(self):
        # Patron with a username
        self.api.enqueue("dump.success.html")
        p = self._patron()
        self.api.update_patron(p, "12345678901234")
        eq_("10", p.external_type)
        eq_("44444444444447", p.authorization_identifier)
        eq_("alice", p.username)
        expiration = date(2059, 4, 1)
        eq_(expiration, p.authorization_expires)

        # Patron with no username
        self.api.enqueue("dump.success_no_username.html")
        p = self._patron()
        self.api.update_patron(p, "12345678901234")
        eq_("10", p.external_type)
        eq_("44444444444448", p.authorization_identifier)
        eq_(None, p.username)
        expiration = date(2059, 4, 1)
        eq_(expiration, p.authorization_expires)

    def test_update_patron_authorization_identifiers(self):
        p = self._patron()

        # If the patron is new, and logged in with a username, we'll use
        # one of their barcodes as their authorization identifier.

        p.authorization_identifier = None
        self.api.enqueue("dump.two_barcodes.html")
        self.api.update_patron(p, "alice")
        eq_("SECOND_barcode", p.authorization_identifier)

        # If the patron is new, and logged in with a barcode, their
        # authorization identifier will be the barcode they used.

        p.authorization_identifier = None
        self.api.enqueue("dump.two_barcodes.html")
        self.api.update_patron(p, "FIRST_barcode")
        eq_("FIRST_barcode", p.authorization_identifier)

        p.authorization_identifier = None
        self.api.enqueue("dump.two_barcodes.html")
        self.api.update_patron(p, "SECOND_barcode")
        eq_("SECOND_barcode", p.authorization_identifier)

        # If the patron has an authorization identifier, but it's not one of the
        # barcodes, we'll replace it the same way we would determine the
        # authorization identifier for a new patron.

        p.authorization_identifier = "abcd"
        self.api.enqueue("dump.two_barcodes.html")
        self.api.update_patron(p, "alice")
        eq_("SECOND_barcode", p.authorization_identifier)

        p.authorization_identifier = "abcd"
        self.api.enqueue("dump.two_barcodes.html")
        self.api.update_patron(p, "FIRST_barcode")
        eq_("FIRST_barcode", p.authorization_identifier)

        p.authorization_identifier = "abcd"
        self.api.enqueue("dump.two_barcodes.html")
        self.api.update_patron(p, "SECOND_barcode")
        eq_("SECOND_barcode", p.authorization_identifier)

        # If the patron has an authorization identifier, and it _is_ one of
        # the barcodes, we'll keep it.

        p.authorization_identifier = "FIRST_barcode"
        self.api.enqueue("dump.two_barcodes.html")
        self.api.update_patron(p, "alice")
        eq_("FIRST_barcode", p.authorization_identifier)

        p.authorization_identifier = "SECOND_barcode"
        self.api.enqueue("dump.two_barcodes.html")
        self.api.update_patron(p, "FIRST_barcode")
        eq_("SECOND_barcode", p.authorization_identifier)

        # If somehow they ended up with their username as an authorization
        # identifier, we'll replace it.

        p.authorization_identifier = "alice"
        self.api.enqueue("dump.two_barcodes.html")
        self.api.update_patron(p, "alice")
        eq_("SECOND_barcode", p.authorization_identifier)

    def test_authenticated_patron_success(self):
        # Patron is valid, but not in our database yet
        self.api.enqueue("dump.success.html")
        self.api.enqueue("pintest.good.html")
        alice = self.api.authenticated_patron(self._db, dict(username="alice", password="4444"))
        eq_("44444444444447", alice.authorization_identifier)
        eq_("alice", alice.username)

        # Create another patron who has a different barcode and username,
        # to verify that our authentication mechanism chooses the right patron
        # and doesn't look up whoever happens to be in the database.
        p = self._patron()
        p.username = 'notalice'
        p.authorization_identifier='111111111111'
        self._db.commit()

        # Patron is in the db, now authenticate with barcode
        self.api.enqueue("pintest.good.html")
        alice = self.api.authenticated_patron(self._db, dict(username="44444444444447", password="4444"))
        eq_("44444444444447", alice.authorization_identifier)
        eq_("alice", alice.username)

        # Authenticate with username again
        self.api.enqueue("pintest.good.html")
        alice = self.api.authenticated_patron(self._db, dict(username="alice", password="4444"))
        eq_("44444444444447", alice.authorization_identifier)
        eq_("alice", alice.username)

    def test_authenticated_patron_renewed_card(self):
        now = datetime.utcnow()
        one_hour_ago = now - timedelta(seconds=3600)
        one_week_ago = now - timedelta(days=7)

        # Patron is in the database.
        p = self._patron()
        p.authorization_identifier = "44444444444447"

        # We checked them against the ILS one hour ago.
        p.last_external_sync = one_hour_ago

        # Normally, calling authenticated_patron only performs a sync
        # and updates last_external_sync if the last sync was twelve
        # hours ago.
        self.api.enqueue("pintest.good.html")
        auth = dict(username="44444444444447", password="4444")
        p2 = self.api.authenticated_patron(self._db, auth)
        eq_(p2, p)
        eq_(p2.last_external_sync, one_hour_ago)

        # However, if the card has expired, a sync is performed every
        # time.
        p.authorization_expires = one_week_ago
        self.api.enqueue("dump.success.html")
        self.api.enqueue("pintest.good.html")
        p2 = self.api.authenticated_patron(self._db, auth)
        eq_(p2, p)

        # Since the sync was performed, last_external_sync was updated.
        assert p2.last_external_sync > one_hour_ago

        # And the patron's card is no longer expired.
        expiration = date(2059, 4, 1)
        eq_(expiration, p.authorization_expires)

    def test_authentication_patron_invalid_expiration_date(self):
        p = self._patron()
        p.authorization_identifier = "44444444444447"
        self.api.enqueue("dump.invalid_expiration.html")
        self.api.enqueue("pintest.good.html")
        auth = dict(username="44444444444447", password="4444")
        p2 = self.api.authenticated_patron(self._db, auth)
        eq_(p2, p)

    def test_patron_info(self):
        self.api.enqueue("dump.success.html")
        patron_info = self.api.patron_info("alice")
        eq_("44444444444447", patron_info.get('barcode'))
        eq_("alice", patron_info.get('username'))

    def test_first_value_takes_precedence(self):
        """This patron has two authorization identifiers.
        The second one takes precedence.
        """
        self.api.enqueue("dump.two_barcodes.html")
        patron_info = self.api.patron_info("alice")
        eq_("SECOND_barcode", patron_info.get('barcode'))
        
    def test_authorization_identifier_blacklist(self):
        """This patron has two authorization identifiers, but the second one
        contains a blacklisted string. The first takes precedence.
        """
        api = MockAPI(authorization_blacklist=["second"])
        api.enqueue("dump.two_barcodes.html")
        patron_info = api.patron_info("alice")
        eq_("FIRST_barcode", patron_info.get('barcode'))

    def test_blacklist_may_remove_every_authorization_identifier(self):
        """A patron may end up with no authorization identifier whatsoever
        because they're all blacklisted.
        """
        api = MockAPI(authorization_blacklist=["barcode"])
        api.enqueue("dump.two_barcodes.html")
        patron_info = api.patron_info("alice")
        eq_(None, patron_info.get('barcode'))

