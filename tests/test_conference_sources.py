import unittest
from unittest import mock

from scripts.collect_papers import (
    ConferenceSource,
    dblp_sparql_query,
    fetch_dblp_conference,
    fetch_dblp_sparql,
    parse_conference_sources,
    parse_dblp_sparql,
    parse_dblp_html_toc,
)
import datetime as dt
import urllib.error


class ConferenceSourceTest(unittest.TestCase):
    def source(self, **overrides):
        values = dict(
            id="vldb", name="VLDB", group="databases",
            dblp_toc_patterns=["db/journals/pvldb/pvldb{volume}.bht"],
            years=[2026, 2025], dblp_volume_offset=2007,
        )
        values.update(overrides)
        return ConferenceSource(**values)

    @mock.patch("scripts.collect_papers.time.sleep")
    @mock.patch("scripts.collect_papers.fetch_dblp_sparql")
    def test_volume_tocs_follow_each_conference_year(self, fetch_json, sleep):
        fetch_json.return_value = {"results": {"bindings": []}}
        fetch_dblp_conference(self.source(), 100)
        queries = [call.args[0] for call in fetch_json.call_args_list]
        self.assertIn("<https://dblp.org/db/journals/pvldb/pvldb19>", queries[0])
        self.assertIn("<https://dblp.org/db/journals/pvldb/pvldb18>", queries[1])
        self.assertEqual(len(queries), 2)

    def test_source_config_preserves_volume_offset(self):
        sources = parse_conference_sources({"conference_sources": {
            "enabled": True, "lookback_years": 2,
            "venues": [{"id": "sigmod", "name": "SIGMOD",
                        "dblp_toc_patterns": ["db/journals/pacmmod/pacmmod{volume}.bht"],
                        "dblp_volume_offset": 2022}],
        }}, dt.datetime(2026, 10, 21, tzinfo=dt.timezone.utc))
        self.assertEqual(sources[0].dblp_volume_offset, 2022)
        self.assertEqual(sources[0].years, [2026, 2025])

    @mock.patch("scripts.collect_papers.fetch_dblp_html_toc")
    @mock.patch("scripts.collect_papers.fetch_dblp_json")
    @mock.patch("scripts.collect_papers.fetch_dblp_sparql")
    def test_empty_sparql_does_not_request_blocked_website(self, sparql, rest, html):
        sparql.return_value = {"results": {"bindings": []}}
        self.assertEqual(fetch_dblp_conference(self.source(years=[2026]), 100), [])
        rest.assert_not_called()
        html.assert_not_called()

    def test_html_accepts_journal_articles_and_extra_attributes(self):
        html = '''<li id="journals/pvldb/Example26" class="entry article toc" data-kind="paper">
          <span class="title" itemprop="name">Retrieval for Agent Memory.</span>
          <li class="ee"><a href="https://example.org/paper.pdf">PDF</a></li>
        </li><li class="entry inproceedings" data-kind="paper" id="conf/vldb/Other26">
          <span class="title">LLM Knowledge Retrieval.</span>
        </li>'''
        papers = parse_dblp_html_toc(html, self.source(), 2026, "db/journals/pvldb/pvldb19.bht")
        self.assertEqual([p["title"] for p in papers], [
            "Retrieval for Agent Memory", "LLM Knowledge Retrieval",
        ])
        self.assertEqual(papers[0]["conference"]["name"], "VLDB")
        self.assertEqual(papers[0]["pdf_url"], "https://example.org/paper.pdf")

    def test_automated_access_challenge_is_reported(self):
        with self.assertRaisesRegex(RuntimeError, "automated-access challenge"):
            parse_dblp_html_toc('<script id="anubis_challenge"></script>', self.source(), 2026, "toc")

    @mock.patch("scripts.collect_papers.fetch_dblp_sparql")
    def test_failed_request_does_not_return_incomplete_year(self, sparql):
        sparql.side_effect = RuntimeError("SPARQL unavailable")
        with self.assertRaisesRegex(RuntimeError, "SPARQL unavailable"):
            fetch_dblp_conference(self.source(), 100)
        sparql.assert_called_once()

    def row(self, key, **fields):
        return {name: {"value": value} for name, value in {
            "paper": f"https://dblp.org/rec/{key}", "title": "Agent Memory.", **fields,
        }.items()}

    def test_sparql_rows_merge_authors_in_signature_order(self):
        data = {"results": {"bindings": [
            self.row("journals/pvldb/Example26", author="Second", ordinal="2", doi="https://doi.org/10.1/test"),
            self.row("journals/pvldb/Example26", author="First", ordinal="1", ee="https://example.org/paper"),
            self.row("journals/pvldb/Example26", author="Second", ordinal="2", pages="1-10"),
            self.row("journals/pvldb/NoAuthors26"),
        ]}}
        papers = parse_dblp_sparql(data, self.source(), 2026, "db/journals/pvldb/pvldb19.bht")
        self.assertEqual(len(papers), 2)
        self.assertEqual(papers[0]["id"], "dblp:journals/pvldb/Example26")
        self.assertEqual(papers[0]["authors"], ["First", "Second"])
        self.assertEqual(papers[0]["pdf_url"], "https://example.org/paper")
        self.assertEqual(papers[0]["conference"]["doi"], "https://doi.org/10.1/test")
        self.assertEqual(papers[0]["conference"]["pages"], "1-10")
        self.assertEqual(papers[1]["authors"], [])

    @mock.patch("scripts.collect_papers.time.sleep")
    @mock.patch("scripts.collect_papers.fetch_dblp_sparql")
    def test_pagination_counts_papers_instead_of_author_rows_and_honors_cap(self, sparql, sleep):
        sparql.side_effect = [
            {"results": {"bindings": [
                self.row(f"journals/pvldb/P{i}", author=name, ordinal=str(n))
                for i in range(200) for n, name in enumerate(["First", "Second"], 1)
            ]}},
            {"results": {"bindings": [self.row("journals/pvldb/Last")]}}
        ]
        papers = fetch_dblp_conference(self.source(years=[2026]), 201)
        self.assertEqual(len(papers), 201)
        self.assertIn("LIMIT 200 OFFSET 0", sparql.call_args_list[0].args[0])
        self.assertIn("LIMIT 1 OFFSET 200", sparql.call_args_list[1].args[0])
        self.assertEqual(sparql.call_count, 2)

    def test_query_uses_exact_toc_and_paper_types_and_rejects_invalid_paths(self):
        query = dblp_sparql_query("db/conf/acl/acl2025-1.bht", 10, 0)
        self.assertIn("dblp:listedOnTocPage <https://dblp.org/db/conf/acl/acl2025-1>", query)
        self.assertIn("dblp:Inproceedings dblp:Article", query)
        with self.assertRaises(ValueError):
            dblp_sparql_query("db/conf/acl/> ?s ?p ?o", 10, 0)

    @mock.patch("scripts.collect_papers.urllib.request.urlopen")
    def test_request_uses_official_endpoint_and_sparql_json_accept_header(self, urlopen):
        urlopen.return_value.__enter__.return_value.read.return_value = b'{"results":{"bindings":[]}}'
        self.assertEqual(fetch_dblp_sparql("SELECT * WHERE {}"), {"results": {"bindings": []}})
        request = urlopen.call_args.args[0]
        self.assertTrue(request.full_url.startswith("https://sparql.dblp.org/sparql?query="))
        self.assertEqual(request.get_header("Accept"), "application/sparql-results+json")

    @mock.patch("scripts.collect_papers.urllib.request.urlopen")
    def test_non_result_document_is_an_error(self, urlopen):
        urlopen.return_value.__enter__.return_value.read.return_value = b'{"error":"unavailable"}'
        with self.assertRaisesRegex(ValueError, "invalid result"):
            fetch_dblp_sparql("query")

    @mock.patch("scripts.collect_papers.time.sleep")
    @mock.patch("scripts.collect_papers.urllib.request.urlopen")
    def test_rate_limit_respects_retry_after(self, urlopen, sleep):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"results":{"bindings":[]}}'
        urlopen.side_effect = [
            urllib.error.HTTPError("https://sparql.dblp.org/sparql", 429, "Too Many Requests", {"Retry-After": "12"}, None),
            response,
        ]
        fetch_dblp_sparql("query")
        sleep.assert_called_once_with(12.0)
        self.assertEqual(urlopen.call_count, 2)

    @mock.patch("scripts.collect_papers.time.sleep")
    @mock.patch("scripts.collect_papers.fetch_dblp_sparql")
    def test_later_page_failure_does_not_return_partial_papers(self, sparql, sleep):
        sparql.side_effect = [
            {"results": {"bindings": [self.row(f"journals/pvldb/P{i}") for i in range(200)]}},
            RuntimeError("second page failed"),
        ]
        with self.assertRaisesRegex(RuntimeError, "second page failed"):
            fetch_dblp_conference(self.source(years=[2026]), 300)


if __name__ == "__main__":
    unittest.main()
