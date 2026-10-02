"""Tests for messages.py -- pure string composition, no side effects possible."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest  # noqa: E402

import messages  # noqa: E402
import taxonomy  # noqa: E402
import state as state_mod  # noqa: E402

# Every category the state machine considers nudge-worthy must have a message template --
# a category that's surfaceable but has no words to say is the exact "checking in" gap the Operator
# doesn't want.
ALL_NUDGE_WORTHY = state_mod.NUDGE_WORTHY


@pytest.mark.parametrize('category', sorted(ALL_NUDGE_WORTHY))
def test_every_nudge_worthy_category_has_a_message(category):
    msg = messages.compose(category=category, agent='test-agent', effort='Test Effort',
                            reason='some real reason', pr_number=123)
    # 'ada' is the lead recipient -- see messages.RECIPIENT_KINDS. Widened
    # deliberately when Division Leads appeared: some problems are neither a
    # decision for the Operator nor something the agent can perform. Not a relaxed
    # assertion; the contract gained a third kind and says so in the module.
    assert msg['to'] in ('operator', 'test-agent', 'ada')
    assert msg['subject']
    assert msg['body']


def test_unknown_category_raises_not_silently_falls_through():
    with pytest.raises(ValueError):
        messages.compose(category='not_a_real_category', agent='a', effort='E', reason='r')


def test_no_message_template_says_checking_in():
    """The literal anti-pattern from the Operator's brief -- assert none of our own copy regresses
    toward it."""
    banned_phrases = ['checking in', 'just checking', 'quick update', "how's it going",
                       'any update', 'wanted to check']
    for category in sorted(ALL_NUDGE_WORTHY):
        msg = messages.compose(category=category, agent='a', effort='E', reason='r',
                                pr_number=1)
        text = (msg['subject'] + ' ' + msg['body']).lower()
        for phrase in banned_phrases:
            assert phrase not in text, f"{category}'s message contains banned phrase {phrase!r}"


def test_blocked_on_human_names_the_agent_and_the_evidence():
    msg = messages.compose(category='blocked_on_human', agent='pr-12689-availability-in-solr',
                            effort='Solr Availability', reason='PR #12689 is clean, idle 221.9h',
                            pr_number=12689)
    assert 'pr-12689-availability-in-solr' in msg['body']
    assert '221.9h' in msg['body']
    assert msg['to'] == 'operator'


def test_merged_needs_cleanup_goes_to_the_agent_not_mek():
    """The one category that's pure mechanics -- doesn't need to interrupt the Operator at all."""
    msg = messages.compose(category='merged_needs_cleanup', agent='some-agent',
                            effort='Some Effort', reason='PR #1 is MERGED but agent is up')
    assert msg['to'] == 'some-agent'


def test_case_study_tag_appears_when_present():
    msg = messages.compose(category='blocked_on_human', agent='a', effort='Solr',
                            reason='r', case_study='b', pr_number=1)
    assert '(case b)' in msg['subject']


def test_case_study_tag_absent_when_none():
    msg = messages.compose(category='blocked_on_human', agent='a', effort='Solr',
                            reason='r', case_study=None, pr_number=1)
    assert 'case' not in msg['subject'].lower()
