"""Independent CMF comparison contract. No inference or rendering entrypoint."""
from .protocol import (prepare, grouping_view, grouping_template, accept_grouping,
                       prepare_board_review, board_review_template, accept_board_review,
                       check_expansion_gate)

__all__ = ["prepare", "grouping_view", "grouping_template", "accept_grouping", "prepare_board_review",
           "board_review_template", "accept_board_review", "check_expansion_gate"]
