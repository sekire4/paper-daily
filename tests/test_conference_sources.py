import unittest
from unittest import mock

from scripts.collect_papers import (
    ConferenceSource,
    fetch_dblp_conference,
    parse_conference_sources,
    parse_dblp_html_toc,
)
import datetime as dt


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
    @mock.patch("scripts.collect_papers.fetch_dblp_html_toc")
    @mock.patch("scripts.collect_papers.fetch_dblp_json")
    def test_volume_tocs_follow_each_conference_year(self, fetch_json, fetch_html, sleep):
        fetch_json.return_value = {"result": {"hits": {"hit": [
            {"info": {"key": "journals/pvldb/Example", "title": "Agent Memory"}}
        ]}}}
        fetch_dblp_conference(self.source(), 100)
        self.assertEqual(fetch_json.call_args_list, [
            mock.call("toc:db/journals/pvldb/pvldb19.bht:", 100),
            mock.call("toc:db/journals/pvldb/pvldb18.bht:", 100),
        ])
        fetch_html.assert_not_called()

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
    def test_empty_search_checks_actual_toc(self, fetch_json, fetch_html):
        fetch_json.return_value = {"result": {"hits": {"@total": "0"}}}
        fetch_html.return_value = [{"id": "dblp:journals/pvldb/Example", "title": "Agent Memory"}]
        source = self.source(years=[2026])
        papers = fetch_dblp_conference(source, 100)
        self.assertEqual(papers, fetch_html.return_value)
        fetch_html.assert_called_once_with("db/journals/pvldb/pvldb19.bht", source, 2026)

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

    @mock.patch("scripts.collect_papers.fetch_dblp_html_toc")
    @mock.patch("scripts.collect_papers.fetch_dblp_json")
    def test_access_challenge_stops_further_year_requests(self, fetch_json, fetch_html):
        fetch_json.return_value = {"result": {"hits": {"@total": "0"}}}
        fetch_html.side_effect = RuntimeError("DBLP returned an automated-access challenge instead of a paper list")
        with self.assertRaisesRegex(RuntimeError, "automated-access challenge"):
            fetch_dblp_conference(self.source(), 100)
        fetch_json.assert_called_once()
        fetch_html.assert_called_once()


if __name__ == "__main__":
    unittest.main()
