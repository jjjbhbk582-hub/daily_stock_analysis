"""Fail-closed listing-lifecycle admission component, not a trading strategy.

The caller must supply source-backed, time-bounded evidence. This component
neither discovers a complete historical universe nor certifies real execution.
A vendor isST=0 flag is insufficient to certify ordinary-listing status.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,date,time,timedelta,timezone
import re
from typing import Iterable

CHINA=timezone(timedelta(hours=8))
MAINBOARD=re.compile(r'(?:SH(?:600|601|603|605)|SZ(?:000|001|002|003))\d{3}\Z')
STAGES={'ordinary_listed','suspended','delisting_decided','delisting_final','delisted','unknown'}

def _aware(t:datetime)->None:
    if not isinstance(t,datetime) or t.tzinfo is None or t.utcoffset() is None:
        raise ValueError('Evidence and decision times require explicit timezones')

@dataclass(frozen=True)
class StageEvidence:
    symbol:str
    known_from:datetime
    effective_from:datetime
    effective_until:datetime|None
    stage:str
    source:str

    def __post_init__(self):
        _aware(self.known_from);_aware(self.effective_from)
        if self.effective_until is not None:
            _aware(self.effective_until)
            if self.effective_until<self.effective_from:raise ValueError('Reversed effective interval')
        if self.stage not in STAGES or not self.source.strip():raise ValueError('Documented stage and source required')
        if self.stage=='ordinary_listed' and self.effective_until is None:
            raise ValueError('Positive ordinary-status evidence cannot be carried indefinitely')
        if not re.fullmatch(r'[A-Z]{2}\d{6}',self.symbol):raise ValueError('Canonical symbol required')

@dataclass(frozen=True)
class Admission:
    allowed:bool
    reason:str
    evidence_sources:tuple[str,...]=()

def entry_decision(symbol:str,at:datetime,is_st:int,tradestatus:int,
                   evidence:Iterable[StageEvidence])->Admission:
    """Permit entry only with dated affirmative evidence, never absence of a ban.

    A recorded termination decision persists until its source interval is closed
    through a reviewed later event. Ordinary evidence does not silently erase it.
    Existing holdings are not mutated, liquidated, or removed by this function.
    """
    _aware(at)
    if not MAINBOARD.fullmatch(symbol):return Admission(False,'outside_mainboard')
    if is_st not in (-1,0,1) or tradestatus not in (-1,0,1):raise ValueError('Invalid vendor state enum')
    if is_st!=0:return Admission(False,'ST_or_unknown_ST')
    if tradestatus!=1:return Admission(False,'not_confirmed_trading')
    active=[e for e in evidence if e.symbol==symbol and e.known_from<=at
            and e.effective_from<=at and (e.effective_until is None or at<=e.effective_until)]
    retirement=[e for e in active if e.stage in {'delisting_decided','delisting_final','delisted'}]
    if retirement:return Admission(False,'known_retirement_state',tuple(sorted({e.source for e in retirement})))
    blocked=[e for e in active if e.stage in {'suspended','unknown'}]
    if blocked:return Admission(False,'conflicting_or_unknown_listing_state',tuple(sorted({e.source for e in blocked})))
    ordinary=[e for e in active if e.stage=='ordinary_listed']
    if not ordinary:return Admission(False,'ordinary_listing_not_established')
    return Admission(True,'confirmed_ordinary_non_ST',tuple(sorted({e.source for e in ordinary})))

def known_retirement(symbol:str,publication_date:str,final_period_start:str,
                     source:str)->list[StageEvidence]:
    """Date-only disclosure is conservatively known at NEXT local midnight.

    These events can prohibit entry but cannot certify any other date as ordinary.
    No actual delisting end date is invented. Later reversals/relistings require
    separately sourced intervals, not automatic clearing of a retirement flag.
    """
    pub=date.fromisoformat(publication_date);start=date.fromisoformat(final_period_start)
    if start<pub:raise ValueError('This forward-scheduled fixture requires announcement before entry')
    known=datetime.combine(pub+timedelta(days=1),time(),CHINA)
    begin=datetime.combine(start,time(),CHINA)
    return [StageEvidence(symbol,known,known,None,'delisting_decided',source),
            StageEvidence(symbol,known,begin,None,'delisting_final',source)]
