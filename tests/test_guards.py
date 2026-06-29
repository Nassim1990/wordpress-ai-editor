"""Pure-function safety guards: SELECT-only SQL and the wp-content path jail."""

import pytest

from wpctl.models import Site
from wpctl.tools.files import jail_path
from wpctl.tools.options import assert_select_only

SITE = Site(slug="acme", domain="a.com", wp_path="/home/croc/site/public_html")


@pytest.mark.parametrize("sql", [
    "SELECT * FROM wp_options",
    "select option_name from wp_options where option_id < 50",
    "SHOW TABLES",
    "DESCRIBE wp_posts",
])
def test_select_allowed(sql):
    assert_select_only(sql)  # no raise


@pytest.mark.parametrize("sql", [
    "DELETE FROM wp_options",
    "UPDATE wp_options SET option_value='x'",
    "DROP TABLE wp_posts",
    "SELECT 1; DROP TABLE wp_posts",
    "INSERT INTO wp_options VALUES (1)",
    "SELECT * INTO OUTFILE '/tmp/x' FROM wp_users",
])
def test_writes_rejected(sql):
    with pytest.raises(ValueError):
        assert_select_only(sql)


def test_jail_allows_inside_wp_content():
    p = jail_path(SITE, "themes/thegem-child/style.css")
    assert p.endswith("/public_html/wp-content/themes/thegem-child/style.css")


@pytest.mark.parametrize("path", [
    "../wp-config.php",
    "../../../../etc/passwd",
    "themes/../../wp-config.php",
])
def test_jail_blocks_escape(path):
    with pytest.raises(ValueError, match="jail"):
        jail_path(SITE, path)
