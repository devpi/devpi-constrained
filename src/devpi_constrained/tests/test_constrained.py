from bs4 import BeautifulSoup
from devpi_common.metadata import parse_version
from devpi_common.url import URL
from devpi_server import __version__ as _devpi_server_version
import pytest


devpi_server_version = parse_version(_devpi_server_version)


if devpi_server_version < parse_version("6.9.3dev"):
    from test_devpi_server.conftest import gentmp  # noqa: F401
    from test_devpi_server.conftest import httpget  # noqa: F401
    from test_devpi_server.conftest import makemapp  # noqa: F401
    from test_devpi_server.conftest import maketestapp  # noqa: F401
    from test_devpi_server.conftest import makexom
    from test_devpi_server.conftest import mapp
    from test_devpi_server.conftest import pypiurls  # noqa: F401
    from test_devpi_server.conftest import simpypi
    from test_devpi_server.conftest import simpypiserver  # noqa: F401
    from test_devpi_server.conftest import storage_info  # noqa: F401
    from test_devpi_server.conftest import testapp
    (makexom, mapp, simpypi, testapp)  # shut up pyflakes
else:
    pytest_plugins = ["pytest_devpi_server", "test_devpi_server.plugin"]


pytestmark = [
    pytest.mark.nomocking,
    pytest.mark.notransaction]


@pytest.fixture
def xom(request, makexom):
    import devpi_constrained.main
    xom = makexom(plugins=[
        (devpi_constrained.main, None)])
    return xom


@pytest.fixture
def srcindex(mapp, simpypi, testapp):
    mapp.login_root()
    api = mapp.create_index("mirror", indexconfig=dict(
        type="mirror",
        mirror_url=simpypi.simpleurl,
        mirror_cache_expiry=0))
    return api


@pytest.fixture
def constrainedindex(mapp, srcindex):
    api = mapp.create_index(
        "constrained",
        indexconfig=dict(
            type="constrained",
            bases=[srcindex.stagename]))
    return api


def add_proj_versions(simpypi, proj_versions):
    for proj, ver in proj_versions:
        fn = "%s-%s.zip" % (proj, ver)
        simpypi.add_release(proj, pkgver=fn)
        simpypi.add_file("/%s/%s" % (proj, fn), "content %s" % fn)


def test_new_constrained_index(constrainedindex, srcindex, testapp):
    r = testapp.get_json(constrainedindex.index)
    result = r.json['result']
    assert result['type'] == 'constrained'
    assert result['bases'] == [srcindex.stagename]
    assert result['constraints'] == []


def test_invalid_constraints(constrainedindex, mapp, testapp):
    r = testapp.get_json(constrainedindex.index)
    result = r.json['result']
    r = mapp.modify_index(
        constrainedindex.stagename,
        dict(
            result, constraints=['bla,']),
        code=400)
    assert "Error while parsing constrains" in r
    if "\',\'" in r:
        assert 'Expected string_end' in r
    else:
        assert 'bla,' in r
        assert 'Expected end or semicolon' in r


def test_conflicting_constraints(constrainedindex, mapp, testapp):
    r = testapp.get_json(constrainedindex.index)
    result = r.json['result']
    r = mapp.modify_index(
        constrainedindex.stagename,
        dict(
            result, constraints=['bla<2', 'bla<3']),
        code=400)
    assert "Error while parsing constrains: Constraint for 'bla' already exists." in r


def test_constraints_file(constrainedindex, mapp, testapp):
    r = testapp.get_json(constrainedindex.index)
    result = r.json['result']
    r = mapp.modify_index(
        constrainedindex.stagename,
        dict(
            result, constraints='bla<2\nfoo>3\n\n# comment\n'))
    assert r['constraints'] == ['bla<2', 'foo>3']


def test_default_no_block(constrainedindex, mapp, simpypi, testapp):
    add_proj_versions(simpypi, [
        ('devpi', '1.0b2'),
        ('pkg', '1.1'),
        ('pkg', '2.0')])
    r = testapp.get(constrainedindex.simpleindex)
    assert "devpi/" in r.text
    assert "pkg/" in r.text
    assert "<a" in r.text
    for proj in ("devpi", "pkg"):
        mapp.get_simple(proj, code=200)
        assert len(mapp.getreleaseslist(proj)) > 0


@pytest.mark.skipif(
    devpi_server_version < parse_version("6.10"),
    reason="Requires terminalwriter fixture")
def test_export_import(constrainedindex, mapp, makemapp, maketestapp, makexom, srcindex, terminalwriter, tmp_path):
    from devpi_server.importexport import do_export, do_import
    import devpi_constrained.main
    serverdir2 = tmp_path.joinpath("server2")
    xom2 = makexom(
        ["--serverdir", serverdir2],
        plugins=[(devpi_constrained.main, None)])
    mapp2 = makemapp(maketestapp(xom2))
    assert mapp.xom != mapp2.xom
    export_path = tmp_path.joinpath("export")
    do_export(export_path, terminalwriter, mapp.xom)
    xom2.config.args.wait_for_events = False
    do_import(export_path, terminalwriter, xom2)
    with xom2.keyfs.read_transaction():
        constrainedindex2 = xom2.model.getstage(constrainedindex.stagename)
        assert constrainedindex2.ixconfig['bases'] == (srcindex.stagename,)


def test_single_package(constrainedindex, mapp, simpypi, testapp):
    add_proj_versions(simpypi, [
        ('devpi', '1.0b2'),
        ('pkg', '1.1'),
        ('pkg', '2.0')])
    r = testapp.patch_json(constrainedindex.index, [
        'constraints=pkg'])
    assert r.json['result']['constraints'] == ['pkg']
    r = testapp.get(constrainedindex.simpleindex)
    assert "devpi/" in r.text
    assert "<a" in r.text
    assert "pkg/" in r.text
    r = mapp.get_simple("devpi")
    assert "devpi-1.0b2.zip" in r.text
    assert len(mapp.getreleaseslist("devpi")) == 1
    r = mapp.get_simple("pkg")
    assert "pkg-1.1.zip" in r.text
    assert "pkg-2.0.zip" in r.text
    assert len(mapp.getreleaseslist("pkg")) == 2


def test_single_package_all(constrainedindex, mapp, simpypi, testapp):
    add_proj_versions(simpypi, [
        ('devpi', '1.0b2'),
        ('pkg', '1.1'),
        ('pkg', '2.0')])
    r = testapp.patch_json(constrainedindex.index, [
        'constraints=pkg\n*'])
    assert r.json['result']['constraints'] == ['pkg', '*']
    r = testapp.get(constrainedindex.simpleindex)
    assert "devpi/" not in r.text
    assert "<a" in r.text
    assert "pkg/" in r.text
    mapp.get_simple("devpi", code=404)
    testapp.xget(
        404,
        "/%s/%s" % (constrainedindex.stagename, "devpi"), accept="application/json")
    r = mapp.get_simple("pkg")
    assert "pkg-1.1.zip" in r.text
    assert "pkg-2.0.zip" in r.text
    assert len(mapp.getreleaseslist("pkg")) == 2


def test_simple_projects_multiple(constrainedindex, mapp, simpypi, testapp):
    add_proj_versions(simpypi, [
        ('devpi', '1.0b2'),
        ('pkg', '1.1'),
        ('pkg', '2.0'),
        ('hello', '1.0'),
        ('hello', '1.1')])
    r = testapp.patch_json(constrainedindex.index, [
        'constraints=devpi\npkg'])
    assert r.json['result']['constraints'] == ['devpi', 'pkg']
    r = testapp.get(constrainedindex.simpleindex)
    assert "<a" in r.text
    assert "devpi/" in r.text
    assert "pkg/" in r.text
    assert "hello/" in r.text
    r = mapp.get_simple("hello")
    assert "hello-1.0.zip" in r.text
    assert "hello-1.1.zip" in r.text
    assert len(mapp.getreleaseslist("hello")) == 2
    r = mapp.get_simple("devpi")
    assert "devpi-1.0b2.zip" in r.text
    assert len(mapp.getreleaseslist("devpi")) == 1
    r = mapp.get_simple("pkg")
    assert "pkg-1.1.zip" in r.text
    assert "pkg-2.0.zip" in r.text
    assert len(mapp.getreleaseslist("pkg")) == 2


def test_simple_projects_multiple_all(constrainedindex, mapp, simpypi, testapp):
    add_proj_versions(simpypi, [
        ('devpi', '1.0b2'),
        ('pkg', '1.1'),
        ('pkg', '2.0'),
        ('hello', '1.0'),
        ('hello', '1.1')])
    r = testapp.patch_json(constrainedindex.index, [
        'constraints=devpi\npkg\n*'])
    assert r.json['result']['constraints'] == ['devpi', 'pkg', '*']
    r = testapp.get(constrainedindex.simpleindex)
    assert "<a" in r.text
    assert "devpi/" in r.text
    assert "pkg/" in r.text
    assert "hello/" not in r.text
    mapp.get_simple("hello", code=404)
    testapp.xget(
        404,
        "/%s/%s" % (constrainedindex.stagename, "hello"), accept="application/json")
    r = mapp.get_simple("devpi")
    assert "devpi-1.0b2.zip" in r.text
    assert len(mapp.getreleaseslist("devpi")) == 1
    r = mapp.get_simple("pkg")
    assert "pkg-1.1.zip" in r.text
    assert "pkg-2.0.zip" in r.text
    assert len(mapp.getreleaseslist("pkg")) == 2


def test_simple_projects_all(constrainedindex, mapp, simpypi, testapp):
    add_proj_versions(simpypi, [
        ('devpi', '1.0b2'),
        ('pkg', '1.1'),
        ('pkg', '2.0'),
        ('hello', '1.0'),
        ('hello', '1.1')])
    r = testapp.patch_json(constrainedindex.index, [
        'constraints=*'])
    assert r.json['result']['constraints'] == ['*']
    r = testapp.get(constrainedindex.simpleindex)
    assert "<a" not in r.text
    assert "devpi/" not in r.text
    assert "hello/" not in r.text
    assert "pkg/" not in r.text
    for proj in ("devpi", "hello", "pkg"):
        mapp.get_simple(proj, code=404)
        testapp.xget(
            404,
            "/%s/%s" % (constrainedindex.stagename, proj),
            accept="application/json")


@pytest.mark.parametrize("constrain_all", (False, True))
@pytest.mark.parametrize("constraint,expected", [
    ('pkg', ['1.0', '1.1', '2.0']),
    ('pkg>=2', ['2.0']),
    ('pkg<2', ['1.0', '1.1']),
    ('pkg~=1.0', ['1.0', '1.1']),
    ('pkg==1.1', ['1.1']),
    ('pkg!=1.1', ['1.0', '2.0']),
    ('pkg==1.1', ['1.1'])])
def test_versions(constrainedindex, constraint, expected, constrain_all, mapp, simpypi, testapp):
    add_proj_versions(simpypi, [
        ('pkg', '1.0'),
        ('pkg', '1.1'),
        ('pkg', '2.0')])
    if constrain_all:
        r = testapp.patch_json(constrainedindex.index, [
            'constraints=%s\n*' % constraint])
        assert r.json['result']['constraints'] == [constraint, '*']
    else:
        r = testapp.patch_json(constrainedindex.index, [
            'constraints=%s' % constraint])
        assert r.json['result']['constraints'] == [constraint]
    releases = sorted(mapp.getreleaseslist("pkg"))
    assert len(releases) == len(expected)
    for release, version in zip(releases, expected):
        release.endswith("pkg-%s.zip" % version)
    r = mapp.get_simple("pkg")
    pkgnames = [
        URL(a.attrs['href']).basename
        for a in BeautifulSoup(r.text, "html.parser").findAll("a")]
    assert pkgnames == ['pkg-%s.zip' % x for x in reversed(expected)]
