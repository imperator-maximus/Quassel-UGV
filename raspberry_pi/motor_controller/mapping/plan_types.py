"""Typed data structures for mowing lane plans."""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


def _compact(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


@dataclass
class PlanParameters:
    cut_width_m: float
    overlap_m: float
    spacing_m: float
    outer_margin_m: float
    sub_margin_m: float
    max_ring_turn_deg: float
    sub_contour_count: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PlanSegment:
    type: str
    coordinates: List[List[float]]
    length_m: float
    segment_index: Optional[int] = None
    lane_index: Optional[int] = None
    rest_index: Optional[int] = None
    rest_group: Optional[int] = None
    direction: Optional[str] = None
    max_turn_angle_deg: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return _compact(asdict(self))


@dataclass
class TransitionSegment:
    type: str
    transition_index: int
    from_segment_index: int
    to_segment_index: int
    from_type: str
    to_type: str
    safe: bool
    reason: str
    route_kind: str
    coordinates: List[List[float]]
    length_m: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MowingPlan:
    name: str
    parameters: PlanParameters
    lanes: List[PlanSegment] = field(default_factory=list)
    rest_lanes: List[PlanSegment] = field(default_factory=list)
    sequence: List[PlanSegment] = field(default_factory=list)
    transitions: List[TransitionSegment] = field(default_factory=list)
    exclusion_contours: List[Dict[str, Any]] = field(default_factory=list)
    map_payload: Dict[str, Any] = field(default_factory=dict)
    subs: List[Dict[str, Any]] = field(default_factory=list)
    skipped_sharp_lanes: int = 0

    def to_dict(self) -> Dict[str, Any]:
        lanes = [lane.to_dict() for lane in self.lanes]
        rest_lanes = [lane.to_dict() for lane in self.rest_lanes]
        sequence = [segment.to_dict() for segment in self.sequence]
        transitions = [transition.to_dict() for transition in self.transitions]
        unsafe_transitions = len([transition for transition in transitions if not transition["safe"]])
        safe_transition_length = sum(transition["length_m"] for transition in transitions if transition["safe"])
        unsafe_transition_length = sum(transition["length_m"] for transition in transitions if not transition["safe"])
        mow_length = sum(item["length_m"] for item in lanes)
        rest_length = sum(item["length_m"] for item in rest_lanes)
        total_drive_length = mow_length + rest_length + safe_transition_length
        return {
            "success": True,
            "name": self.name,
            "strategy": "hybrid_contour_suboffset_rest_reverse",
            "parameters": self.parameters.to_dict(),
            "lane_count": len(lanes),
            "rest_lane_count": len(rest_lanes),
            "connector_count": 0,
            "transition_count": len(transitions),
            "unsafe_transition_count": unsafe_transitions,
            "skipped_sharp_lanes": self.skipped_sharp_lanes,
            "mow_length_m": round(mow_length, 2),
            "rest_length_m": round(rest_length, 2),
            "connector_length_m": round(safe_transition_length, 2),
            "unsafe_transition_length_m": round(unsafe_transition_length, 2),
            "total_drive_length_m": round(total_drive_length, 2),
            "total_length_m": round(total_drive_length, 2),
            "lanes": lanes,
            "rest_lanes": rest_lanes,
            "sequence": sequence,
            "transitions": transitions,
            "exclusion_contours": self.exclusion_contours,
            "map": self.map_payload,
            "subs": self.subs,
        }
