from bs4 import BeautifulSoup
from devpi_common.metadata import parse_version
from devpi_common.url import URL
from devpi_server import __version__ as _devpi_server_version
import pytest


pytest_plugins = ["pytest_devpi_server", "test_devpi_server.plugin"]


devpi_server_version = parse_version(_devpi_server_version)
pytestmark = [
    pytest.mark.nomocking,
    pytest.mark.notransaction]


@pytest.fixture
def remote_index_info(server_version):
    from devpi_common.metadata import parse_version

    if server_version < parse_version("7.0.0.dev2"):

        class MirrorInfo:
            refresh_option = "mirror_cache_expiry"
            type = "mirror"
            url_option = "mirror_url"

        return MirrorInfo()

    class RemoteInfo:
        refresh_option = "remote_refresh_delay"
        type = "remote"
        url_option = "remote_url"

    return RemoteInfo()


@pytest.fixture
def xom(request, makexom):
    import devpi_constrained.main
    xom = makexom(plugins=[
        (devpi_constrained.main, None)])
    return xom


@pytest.fixture
def srcindex(mapp, remote_index_info, simpypi):
    mapp.login_root()
    api = mapp.create_index(
        "mirror",
        indexconfig={
            "type": remote_index_info.type,
            remote_index_info.url_option: simpypi.simpleurl,
            remote_index_info.refresh_option: 0,
        },
    )
    return api


@pytest.fixture
def constrainedindex(mapp, srcindex):
    api = mapp.create_index(
        "constrained",
        indexconfig=dict(
            type="constrained",
            bases=[srcindex.stagename]))
    return api


@pytest.fixture
def inheritingindex(mapp, constrainedindex):
    return mapp.create_index(
        "inheritingindex", indexconfig=dict(bases=[constrainedindex.stagename])
    )


@pytest.fixture(
    params=[
        pytest.param(False, id="nobase"),
        pytest.param(
            True,
            id="withbase",
            marks=pytest.mark.skipif(
                devpi_server_version < parse_version("7.0.0dev4"),
                reason="Needs inherited filtering",
            ),
        ),
    ]
)
def testindex(constrainedindex, inheritingindex, request):
    return inheritingindex if request.param else constrainedindex


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
        assert "Expected end or semicolon" in r or "Expected semicolon" in r


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


def test_default_no_block(mapp, simpypi, testapp, testindex):
    add_proj_versions(simpypi, [
        ('devpi', '1.0b2'),
        ('pkg', '1.1'),
        ('pkg', '2.0'),
        ('pytz', '2004d')])
    r = testapp.get(testindex.simpleindex)
    assert "devpi/" in r.text
    assert "pkg/" in r.text
    assert "<a" in r.text
    for proj in ("devpi", "pkg"):
        mapp.get_simple(proj, code=200)
        assert len(mapp.getreleaseslist(proj)) > 0


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


def test_single_package(constrainedindex, mapp, simpypi, testapp, testindex):
    add_proj_versions(simpypi, [
        ('devpi', '1.0b2'),
        ('pkg', '1.1'),
        ('pkg', '2.0'),
        ('pytz', '2004d')])
    r = testapp.patch_json(constrainedindex.index, [
        'constraints=pkg'])
    assert r.json['result']['constraints'] == ['pkg']
    r = testapp.get(testindex.simpleindex)
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


def test_single_package_all(constrainedindex, mapp, simpypi, testapp, testindex):
    add_proj_versions(simpypi, [
        ('devpi', '1.0b2'),
        ('pkg', '1.1'),
        ('pkg', '2.0'),
        ('pytz', '2004d')])
    r = testapp.patch_json(constrainedindex.index, [
        'constraints=pkg\n*'])
    assert r.json['result']['constraints'] == ['pkg', '*']
    r = testapp.get(testindex.simpleindex)
    assert "devpi/" not in r.text
    assert "<a" in r.text
    assert "pkg/" in r.text
    mapp.use(testindex.stagename)
    mapp.get_simple("devpi", code=404)
    testapp.xget(
        404,
        "/%s/%s" % (constrainedindex.stagename, "devpi"), accept="application/json")
    r = mapp.get_simple("pkg")
    assert "pkg-1.1.zip" in r.text
    assert "pkg-2.0.zip" in r.text
    assert len(mapp.getreleaseslist("pkg")) == 2


def test_simple_projects_multiple(constrainedindex, mapp, simpypi, testapp, testindex):
    add_proj_versions(simpypi, [
        ('devpi', '1.0b2'),
        ('pkg', '1.1'),
        ('pkg', '2.0'),
        ('hello', '1.0'),
        ('hello', '1.1'),
        ('pytz', '2004d')])
    r = testapp.patch_json(constrainedindex.index, [
        'constraints=devpi\npkg'])
    assert r.json['result']['constraints'] == ['devpi', 'pkg']
    r = testapp.get(testindex.simpleindex)
    assert "<a" in r.text
    assert "devpi/" in r.text
    assert "pkg/" in r.text
    assert "hello/" in r.text
    mapp.use(testindex.stagename)
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


def test_simple_projects_multiple_all(
    constrainedindex, mapp, simpypi, testapp, testindex
):
    add_proj_versions(simpypi, [
        ('devpi', '1.0b2'),
        ('pkg', '1.1'),
        ('pkg', '2.0'),
        ('hello', '1.0'),
        ('hello', '1.1'),
        ('pytz', '2004d')])
    r = testapp.patch_json(constrainedindex.index, [
        'constraints=devpi\npkg\n*'])
    assert r.json['result']['constraints'] == ['devpi', 'pkg', '*']
    r = testapp.get(testindex.simpleindex)
    assert "<a" in r.text
    assert "devpi/" in r.text
    assert "pkg/" in r.text
    assert "hello/" not in r.text
    mapp.use(testindex.stagename)
    mapp.get_simple("hello", code=404)
    testapp.xget(
        404, "/{}/{}".format(testindex.stagename, "hello"), accept="application/json"
    )
    r = mapp.get_simple("devpi")
    assert "devpi-1.0b2.zip" in r.text
    assert len(mapp.getreleaseslist("devpi")) == 1
    r = mapp.get_simple("pkg")
    assert "pkg-1.1.zip" in r.text
    assert "pkg-2.0.zip" in r.text
    assert len(mapp.getreleaseslist("pkg")) == 2


def test_simple_projects_all(constrainedindex, mapp, simpypi, testapp, testindex):
    add_proj_versions(simpypi, [
        ('devpi', '1.0b2'),
        ('pkg', '1.1'),
        ('pkg', '2.0'),
        ('hello', '1.0'),
        ('hello', '1.1'),
        ('pytz', '2004d')])
    r = testapp.patch_json(constrainedindex.index, [
        'constraints=*'])
    assert r.json['result']['constraints'] == ['*']
    r = testapp.get(testindex.simpleindex)
    assert "<a" not in r.text
    assert "devpi/" not in r.text
    assert "hello/" not in r.text
    assert "pkg/" not in r.text
    mapp.use(testindex.stagename)
    for proj in ("devpi", "hello", "pkg"):
        mapp.get_simple(proj, code=404)
        testapp.xget(404, f"/{testindex.stagename}/{proj}", accept="application/json")


def test_constraint_all(constrainedindex, mapp, simpypi, testapp, testindex):
    mapp.use(testindex.stagename)
    all_versions = [
        "2004d",  # legacy non PEP440
        "1.0",
        "1.1",
        "2.0",
    ]
    add_proj_versions(simpypi, [("pkg", v) for v in all_versions])
    r = testapp.patch_json(constrainedindex.index, ["constraints=*"])
    assert r.json["result"]["constraints"] == ["*"]
    assert not mapp.getreleaseslist("pkg", code=404)
    r = mapp.get_simple("pkg", code=404)
    pkgnames = [
        URL(a.attrs["href"]).basename
        for a in BeautifulSoup(r.text, "html.parser").findAll("a")
    ]
    assert pkgnames == []
    with mapp.xom.keyfs.read_transaction():
        index = mapp.xom.model.getstage(testindex.stagename)
        assert index.has_project("pkg") is False
        assert index.list_versions("pkg") == set()
        assert {x.version for x in index.get_releaselinks("pkg")} == set()
        assert {x.version for x in index.get_simplelinks("pkg")} == set()
        for filtered_version in all_versions:
            assert not index.get_versiondata("pkg", filtered_version)


@pytest.mark.parametrize("constrain_all", [False, True])
@pytest.mark.parametrize(("constraint", "expected"), [
    ('pkg', ['2004d', '1.0', '1.1', '2.0']),
    ('pkg>=2', ['2.0']),
    ('pkg<2', ['1.0', '1.1']),
    ('pkg~=1.0', ['1.0', '1.1']),
    ('pkg!=1.1', ['1.0', '2.0']),
    ('pkg==1.1', ['1.1'])])
def test_versions(
    constrainedindex,
    constraint,
    expected,
    constrain_all,
    mapp,
    simpypi,
    testapp,
    testindex,
):
    mapp.use(testindex.stagename)
    all_versions = [
        "2004d",  # legacy non PEP440
        "1.0",
        "1.1",
        "2.0",
    ]
    add_proj_versions(simpypi, [("pkg", v) for v in all_versions])
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
    with mapp.xom.keyfs.read_transaction():
        index = mapp.xom.model.getstage(testindex.stagename)
        assert index.has_project("pkg") is True
        assert index.list_versions("pkg") == set(expected)
        assert {x.version for x in index.get_releaselinks("pkg")} == set(expected)
        assert {x.version for x in index.get_simplelinks("pkg")} == set(expected)
        for filtered_version in set(all_versions).difference(expected):
            assert not index.get_versiondata("pkg", filtered_version)
        for expected_version in expected:
            assert index.get_versiondata("pkg", expected_version)


@pytest.mark.skipif(
    devpi_server_version < parse_version("7.0.0dev4"),
    reason="Needs inherited filtering",
)
@pytest.mark.parametrize(
    ("constraint1", "constraint2", "expected"),
    [
        ("pkg", "pkg!=1.1", ["2004d", "1.0", "1.1", "2.0"]),
        ("pkg>=2", "pkg>=1.1", ["1.1", "2.0"]),
        ("pkg==2", "pkg==1.1", ["1.1", "2.0"]),
        ("pkg==2", "pkg>=2", ["2.0"]),
        ("*", "pkg!=1.1", ["1.0", "2.0"]),
        ("pkg!=1.1", "*", ["1.0", "2.0"]),
    ],
)
def test_complex_inheritance(
    constraint1, constraint2, expected, mapp, simpypi, srcindex
):
    all_versions = [
        "2004d",  # legacy non PEP440
        "1.0",
        "1.1",
        "2.0",
    ]
    add_proj_versions(simpypi, [("pkg", v) for v in all_versions])
    api_c1 = mapp.create_index(
        "constrained1",
        indexconfig=dict(
            type="constrained",
            bases=[srcindex.stagename],
            constraints=constraint1,
        ),
    )
    api_c2 = mapp.create_index(
        "constrained2",
        indexconfig=dict(
            type="constrained",
            bases=[srcindex.stagename],
            constraints=constraint2,
        ),
    )
    api = mapp.create_index(
        "inheriting", indexconfig=dict(bases=[api_c1.stagename, api_c2.stagename])
    )
    mapp.use(api.stagename)
    releases = sorted(mapp.getreleaseslist("pkg"))
    assert len(releases) == len(expected)
    for release, version in zip(releases, expected, strict=True):
        release.endswith(f"pkg-{version}.zip")
    r = mapp.get_simple("pkg")
    pkgnames = [
        URL(a.attrs["href"]).basename
        for a in BeautifulSoup(r.text, "html.parser").findAll("a")
    ]
    assert pkgnames == [f"pkg-{x}.zip" for x in reversed(expected)]
    with mapp.xom.keyfs.read_transaction():
        index = mapp.xom.model.getstage(api.stagename)
        assert index.has_project("pkg") is True
        assert index.list_versions("pkg") == set(expected)
        assert {x.version for x in index.get_releaselinks("pkg")} == set(expected)
        assert {x.version for x in index.get_simplelinks("pkg")} == set(expected)
        for filtered_version in set(all_versions).difference(expected):
            assert not index.get_versiondata("pkg", filtered_version)
        for expected_version in expected:
            assert index.get_versiondata("pkg", expected_version)
