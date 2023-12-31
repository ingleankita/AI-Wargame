from __future__ import annotations
import argparse
import copy
from datetime import datetime
from enum import Enum
from dataclasses import dataclass, field
from time import sleep
from typing import Tuple, TypeVar, Type, Iterable, ClassVar
import random
import requests
import time

# maximum and minimum values for our heuristic scores (usually represents an end of game condition)
MAX_HEURISTIC_SCORE = 2000000000
MIN_HEURISTIC_SCORE = -2000000000
num_evals_per_depth = 0

class UnitType(Enum):
    """Every unit type."""
    AI = 0
    Tech = 1
    Virus = 2
    Program = 3
    Firewall = 4


class Player(Enum):
    """The 2 players."""
    Attacker = 0
    Defender = 1

    def next(self) -> Player:
        """The next (other) player."""
        if self is Player.Attacker:
            return Player.Defender
        else:
            return Player.Attacker


class GameType(Enum):
    AttackerVsDefender = 0
    AttackerVsComp = 1
    CompVsDefender = 2
    CompVsComp = 3


##############################################################################################################

@dataclass
class Unit:
    player: Player = Player.Attacker
    type: UnitType = UnitType.Program
    health: int = 9
    # class variable: damage table for units (based on the unit type constants in order)
    damage_table: ClassVar[list[list[int]]] = [
        [3, 3, 3, 3, 1],  # AI
        [1, 1, 6, 1, 1],  # Tech
        [9, 6, 1, 6, 1],  # Virus
        [3, 3, 3, 3, 1],  # Program
        [1, 1, 1, 1, 1],  # Firewall
    ]
    # class variable: repair table for units (based on the unit type constants in order)
    repair_table: ClassVar[list[list[int]]] = [
        [0, 1, 1, 0, 0],  # AI
        [3, 0, 0, 3, 3],  # Tech
        [0, 0, 0, 0, 0],  # Virus
        [0, 0, 0, 0, 0],  # Program
        [0, 0, 0, 0, 0],  # Firewall
    ]

    def is_alive(self) -> bool:
        """Are we alive ?"""
        return self.health > 0

    def mod_health(self, health_delta: int):
        """Modify this unit's health by delta amount."""
        self.health += health_delta
        if self.health < 0:
            self.health = 0
        elif self.health > 9:
            self.health = 9

    def to_string(self) -> str:
        """Text representation of this unit."""
        p = self.player.name.lower()[0]
        t = self.type.name.upper()[0]
        return f"{p}{t}{self.health}"

    def __str__(self) -> str:
        """Text representation of this unit."""
        return self.to_string()

    def damage_amount(self, target: Unit) -> int:
        """How much can this unit damage another unit."""
        amount = self.damage_table[self.type.value][target.type.value]
        if target.health - amount < 0:
            return target.health
        return amount

    def repair_amount(self, target: Unit) -> int:
        """How much can this unit repair another unit."""
        amount = self.repair_table[self.type.value][target.type.value]
        if target.health + amount > 9:
            return 9 - target.health
        return amount


##############################################################################################################

@dataclass
class Coord:
    """Representation of a game cell coordinate (row, col)."""
    row: int = 0
    col: int = 0

    def col_string(self) -> str:
        """Text representation of this Coord's column."""
        coord_char = '?'
        if self.col < 16:
            coord_char = "0123456789abcdef"[self.col]
        return str(coord_char)

    def row_string(self) -> str:
        """Text representation of this Coord's row."""
        coord_char = '?'
        if self.row < 26:
            coord_char = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[self.row]
        return str(coord_char)

    def to_string(self) -> str:
        """Text representation of this Coord."""
        return self.row_string() + self.col_string()

    def __str__(self) -> str:
        """Text representation of this Coord."""
        return self.to_string()

    def clone(self) -> Coord:
        """Clone a Coord."""
        return copy.copy(self)

    def iter_range(self, dist: int) -> Iterable[Coord]:
        """Iterates over Coords inside a rectangle centered on our Coord."""
        for row in range(self.row - dist, self.row + 1 + dist):
            for col in range(self.col - dist, self.col + 1 + dist):
                yield Coord(row, col)

    def iter_adjacent(self) -> Iterable[Coord]:
        """Iterates over adjacent Coords."""
        yield Coord(self.row - 1, self.col)
        yield Coord(self.row, self.col - 1)
        yield Coord(self.row + 1, self.col)
        yield Coord(self.row, self.col + 1)

    @classmethod
    def from_string(cls, s: str) -> Coord | None:
        """Create a Coord from a string. ex: D2."""
        s = s.strip()
        for sep in " ,.:;-_":
            s = s.replace(sep, "")
        if (len(s) == 2):
            coord = Coord()
            coord.row = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".find(s[0:1].upper())
            coord.col = "0123456789abcdef".find(s[1:2].lower())
            return coord
        else:
            return None


##############################################################################################################

@dataclass
class CoordPair:
    """Representation of a game move or a rectangular area via 2 Coords."""
    src: Coord = field(default_factory=Coord)
    dst: Coord = field(default_factory=Coord)

    def to_string(self) -> str:
        """Text representation of a CoordPair."""
        return self.src.to_string() + " " + self.dst.to_string()

    def __str__(self) -> str:
        """Text representation of a CoordPair."""
        return self.to_string()

    def clone(self) -> CoordPair:
        """Clones a CoordPair."""
        return copy.copy(self)

    def iter_rectangle(self) -> Iterable[Coord]:
        """Iterates over cells of a rectangular area."""
        for row in range(self.src.row, self.dst.row + 1):
            for col in range(self.src.col, self.dst.col + 1):
                yield Coord(row, col)

    @classmethod
    def from_quad(cls, row0: int, col0: int, row1: int, col1: int) -> CoordPair:
        """Create a CoordPair from 4 integers."""
        return CoordPair(Coord(row0, col0), Coord(row1, col1))

    @classmethod
    def from_dim(cls, dim: int) -> CoordPair:
        """Create a CoordPair based on a dim-sized rectangle."""
        return CoordPair(Coord(0, 0), Coord(dim - 1, dim - 1))

    @classmethod
    def from_string(cls, s: str) -> CoordPair | None:
        """Create a CoordPair from a string. ex: A3 B2"""
        s = s.strip()
        for sep in " ,.:;-_":
            s = s.replace(sep, "")
        if (len(s) == 4):
            coords = CoordPair()
            coords.src.row = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".find(s[0:1].upper())
            coords.src.col = "0123456789abcdef".find(s[1:2].lower())
            coords.dst.row = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".find(s[2:3].upper())
            coords.dst.col = "0123456789abcdef".find(s[3:4].lower())
            return coords
        else:
            return None


##############################################################################################################

@dataclass
class Options:
    """Representation of the game options."""
    dim: int = 5
    max_depth: int | None = 4
    min_depth: int | None = 2
    max_time: float | None = 5.0
    game_type: GameType = GameType.AttackerVsDefender
    alpha_beta: bool = True
    max_turns: int | None = 100
    randomize_moves: bool = True
    broker: str | None = None


##############################################################################################################

@dataclass
class Stats:
    """Representation of the global game statistics."""
    evaluations_per_depth: dict[int, int] = field(default_factory=dict)
    total_seconds: float = 0.0


##############################################################################################################

def evaluate_e0(node) -> int:
    """Evaluate heuristic value of state depending on choice of e0 TODO: Heuristics"""
    # This function consider the total units a player currently has on the board. All units are of equal weight except for AI

    h_score = 0

    # Get Player unit and count
    attacker_unit_type = [0, 0, 0, 0, 0]  # Count of Attacker's unit types
    defender_unit_type = [0, 0, 0, 0, 0]  # Count of Defender's unit types

    # Count the number of units for each unit type
    for row in range(len(node.board)):
        for col in range(len(node.board[row])):
            if node.board[row][col]:
                unit = node.board[row][col]
                # For Attacker
                if unit.player == Player.Attacker:
                    attacker_unit_type[unit.type.value] += 1
                # For Defender
                elif unit.player == Player.Defender:
                    defender_unit_type[unit.type.value] += 1

    attacker = 3 * attacker_unit_type[1] + 3 * attacker_unit_type[2] + 3 * attacker_unit_type[3] + 3 * \
               attacker_unit_type[4] + 9999 * attacker_unit_type[0]
    defender = 3 * defender_unit_type[1] + 3 * defender_unit_type[2] + 3 * defender_unit_type[3] + 3 * \
               defender_unit_type[4] + 9999 * defender_unit_type[0]

    h_score = attacker - defender
    return max(MIN_HEURISTIC_SCORE, min(h_score, MAX_HEURISTIC_SCORE))


def evaluate_e1(node) -> int:
    """Evaluate heuristic value of state depending on choice of e1"""
    # This heuristic considers 4 features: a player's number of unit, unit health, and unit proximity to the opponent's AI.
    # Each feature is assigned with a weight: health > number of unit > proximity to opponent AI
    # Each unit type also has its own weight

    h_score = 0

    # Get player units and counts
    attacker_units = list(node.player_units(Player.Attacker))
    defender_units = list(node.player_units(Player.Defender))

    # Find positions of the attacker's AI and the defender's AI
    attacker_ai_position = None
    defender_ai_position = None
    for row in range(len(node.board)):
        for col in range(len(node.board[row])):
            if node.board[row][col]:
                unit = node.board[row][col]
                if unit.type == UnitType.AI:
                    if unit.player == Player.Attacker:
                        attacker_ai_position = (row, col)
                    if unit.player == Player.Defender:
                        defender_ai_position = (row, col)

    UNIT_TYPE_WEIGHT = [9999, 500, 500, 20, 100]  # A - V - T - P - F
    WEIGHT_HEALTH = 5  # Total health of all units
    WEIGHT_COUNT_UNIT = 3  # Total number of units
    WEIGHT_DISTANCE_TO_AI = 2  # Total distance from all units to opponent's AI

    # Evaluate heuristic score for attcker's unit
    for coord, unit in attacker_units:
        # Calculate the estimated distance from unit to defender's AI = difference in row + difference in column
        if defender_ai_position:
            distance_to_defender_ai = abs(coord.row - defender_ai_position[0]) + abs(
                coord.col - defender_ai_position[1])
        else:
            distance_to_defender_ai = 0
        # The greater the distance -> the further attacker's units is from defender's AI, the less advantage it has -> Minus distance to h_score
        h_score -= distance_to_defender_ai * WEIGHT_DISTANCE_TO_AI
        h_score += UNIT_TYPE_WEIGHT[unit.type.value] * WEIGHT_COUNT_UNIT
        h_score += unit.health * UNIT_TYPE_WEIGHT[unit.type.value] * WEIGHT_HEALTH

    # Evaluate heuristic score for defender's unit
    for coord, unit in defender_units:
        # Calculate the estimated distance from unit to Attacker's AI = difference in row + difference in column
        if attacker_ai_position:
            distance_to_attacker_ai = abs(coord.row - attacker_ai_position[0]) + abs(
                coord.col - attacker_ai_position[1])
        else:
            distance_to_attacker_ai = 0
        # The greater the distance -> the further defender's units is from attaker's AI, the more avantage it has -> Plus distance to h_score
        h_score += distance_to_attacker_ai * WEIGHT_DISTANCE_TO_AI
        h_score -= UNIT_TYPE_WEIGHT[unit.type.value] * WEIGHT_COUNT_UNIT
        h_score -= unit.health * UNIT_TYPE_WEIGHT[unit.type.value] * WEIGHT_HEALTH

    return max(MIN_HEURISTIC_SCORE, min(h_score, MAX_HEURISTIC_SCORE))


def evaluate_e2(node) -> int:
    """Evaluate heuristic value of state depending on choice of e2"""
    # Consider how spaced-out all attacker's unit is compared to defender's units
    h_score = 0

    # Get player units and counts
    attacker_units = list(node.player_units(Player.Attacker))
    defender_units = list(node.player_units(Player.Defender))

    # Estimate the total distance between all attacker units i.e how spaced-out the units is. The more spaced-out the attacker's units the more favorable - more change of attack
    # Method: summation of total distance between all pairs of attacker units
    attack_unit_space_out = 0
    for coord1, _ in attacker_units:
        for coord2, _ in attacker_units:
            if coord1 != coord2:  # Avoid comparing the same unit to itself
                distance = abs(coord1.row - coord2.row) + abs(coord1.col - coord2.col)
                attack_unit_space_out += distance

    # Estimate the total distance between all defender units i.e how spaced-out the units is. The more spaced-out the attacker's units the less favorable - less chance of repair
    # Method: summation of total distance between all pairs of attacker units
    defender_unit_space_out = 0
    for coord1, _ in defender_units:
        for coord2, _ in defender_units:
            if coord1 != coord2:  # Avoid comparing the same unit to itself
                distance = abs(coord1.row - coord2.row) + abs(coord1.col - coord2.col)
                defender_unit_space_out += distance

    # The more spaced-out attacker units -> the more advantage. The more spaced-out defender units -> the less advantage, since it's cannot repair
    h_score = attack_unit_space_out - defender_unit_space_out

    return max(MIN_HEURISTIC_SCORE, min(h_score, MAX_HEURISTIC_SCORE))


def minimax(node, depth, maximizing_player) -> Tuple[int, CoordPair, float]:
    """TODO: Minimax"""
    if depth == 0 or node.is_finished():
        global num_evals_per_depth
        num_evals_per_depth += 1
        return evaluate_e0(node), None, 0
    if maximizing_player:
        num_evals_per_depth = 0
        v = float('-inf')
        best_move = None
        for child, move in list(generate_children(node)):
            score, _1, _2 = minimax(child, depth - 1, False)
            if score > v:
                v = score
                best_move = move
        return v, best_move, _2
    else:
        num_evals_per_depth = 0
        v = float('inf')
        for child, move in list(generate_children(node)):
            score, _1, _2 = minimax(child, depth - 1, False)
            if score < v:
                v = score
                best_move = move
        return v, best_move, _2


def alphabeta(node, depth, alpha, beta, maximizing_player) -> Tuple[int, CoordPair, float]:
    """TODO: Alpha-Beta"""
    if depth == 0 or node.is_finished():
        global num_evals_per_depth
        num_evals_per_depth += 1
        return evaluate_e0(node), None, 0
    if maximizing_player:
        num_evals_per_depth = 0
        v = float('-inf')
        best_move = None
        for child, move in list(generate_children(node)):
            score, _1, _2 = alphabeta(child, depth - 1, alpha, beta, False)
            if score > v:
                v = score
                best_move = move
            alpha = max(alpha, v)
            if beta <= alpha:
                break
        return v, best_move, _2
    else:
        num_evals_per_depth = 0
        v = float('inf')
        best_move = None
        for child, move in list(generate_children(node)):
            score, _1, _2 = alphabeta(child, depth - 1, alpha, beta, True)
            if score < v:
                v = score
                best_move = move
            beta = min(beta, v)
            if beta <= alpha:
                break
        return v, best_move, _2


def generate_children(node) -> Iterable[CoordPair]:  # Generates all children of a node
    cells = CoordPair(Coord(0, 0), Coord(4, 4))  # Get range of start and end coordinates
    for i in cells.iter_rectangle():
        for j in cells.iter_rectangle():
            coords = CoordPair(i, j)
            if node.is_valid_move(coords):  # Check if move is valid
                child = node.clone()
                perform_move = child.perform_move(coords)
                perform_move_success, result = perform_move
                if perform_move_success:  # If move could be performed successfully
                    yield child, coords


@dataclass
class Game:
    """Representation of the game state."""
    board: list[list[Unit | None]] = field(default_factory=list)
    next_player: Player = Player.Attacker
    turns_played: int = 0
    options: Options = field(default_factory=Options)
    stats: Stats = field(default_factory=Stats)
    _attacker_has_ai: bool = True
    _defender_has_ai: bool = True

    def __post_init__(self):
        """Automatically called after class init to set up the default board state."""
        dim = self.options.dim
        self.board = [[None for _ in range(dim)] for _ in range(dim)]
        md = dim - 1
        self.set(Coord(0, 0), Unit(player=Player.Defender, type=UnitType.AI))
        self.set(Coord(1, 0), Unit(player=Player.Defender, type=UnitType.Tech))
        self.set(Coord(0, 1), Unit(player=Player.Defender, type=UnitType.Tech))
        self.set(Coord(2, 0), Unit(player=Player.Defender, type=UnitType.Firewall))
        self.set(Coord(0, 2), Unit(player=Player.Defender, type=UnitType.Firewall))
        self.set(Coord(1, 1), Unit(player=Player.Defender, type=UnitType.Program))
        self.set(Coord(md, md), Unit(player=Player.Attacker, type=UnitType.AI))
        self.set(Coord(md - 1, md), Unit(player=Player.Attacker, type=UnitType.Virus))
        self.set(Coord(md, md - 1), Unit(player=Player.Attacker, type=UnitType.Virus))
        self.set(Coord(md - 2, md), Unit(player=Player.Attacker, type=UnitType.Program))
        self.set(Coord(md, md - 2), Unit(player=Player.Attacker, type=UnitType.Program))
        self.set(Coord(md - 1, md - 1), Unit(player=Player.Attacker, type=UnitType.Firewall))

    def get_attacker_units(self) -> Iterable[Unit]:
        for row in range(len(self.board)):
            for col in range(len(self.board[row])):
                if self.board[row][col] and self.board[row][col].player is Player.Attacker:
                    yield self.board[row][col]

    def get_defender_units(self) -> Iterable[Unit]:
        for row in range(len(self.board)):
            for col in range(len(self.board[row])):
                if self.board[row][col] and self.board[row][col].player is Player.Defender:
                    yield self.board[row][col]

    def get_units(self):
        for row in range(len(self.board)):
            for col in range(len(self.board[row])):
                if self.board[row][col]:
                    print(self.board[row][col].to_string())

    def clone(self) -> Game:
        """Make a new copy of a game for minimax recursion.

        Shallow copy of everything except the board (options and stats are shared).
        """
        new = copy.copy(self)
        new.board = copy.deepcopy(self.board)
        return new

    def is_empty(self, coord: Coord) -> bool:
        """Check if contents of a board cell of the game at Coord is empty (must be valid coord)."""
        return self.board[coord.row][coord.col] is None

    def get(self, coord: Coord) -> Unit | None:
        """Get contents of a board cell of the game at Coord."""
        if self.is_valid_coord(coord):
            return self.board[coord.row][coord.col]
        else:
            return None

    def set(self, coord: Coord, unit: Unit | None):
        """Set contents of a board cell of the game at Coord."""
        if self.is_valid_coord(coord):
            self.board[coord.row][coord.col] = unit

    def remove_dead(self, coord: Coord):
        """Remove unit at Coord if dead."""
        unit = self.get(coord)
        if unit is not None and not unit.is_alive():
            self.set(coord, None)
            if unit.type == UnitType.AI:
                if unit.player == Player.Attacker:
                    self._attacker_has_ai = False
                else:
                    self._defender_has_ai = False

    def mod_health(self, coord: Coord, health_delta: int):
        """Modify health of unit at Coord (positive or negative delta)."""
        target = self.get(coord)
        if target is not None:
            target.mod_health(health_delta)
            self.remove_dead(coord)

    def is_valid_move(self, coords: CoordPair) -> bool:
        """Validate a move expressed as a CoordPair."""

        # Check if unit is engaged in combat
        adj_coords = list(coords.src.iter_adjacent())
        up = adj_coords[0]
        left = adj_coords[1]
        down = adj_coords[2]
        right = adj_coords[3]

        # Get unit at src
        unit = self.get(coords.src)

        if not self.board[coords.src.row][coords.src.col]:
            return False

        # Validate if there CoordPair is within the board dimension
        if not self.is_valid_coord(coords.src) or not self.is_valid_coord(coords.dst):
            return False

        # Validate if dst is only up, down, left, or right and not diagonal
        if (coords.dst not in adj_coords and coords.dst != coords.src):
            return False

        # Validate if dst is only up, down, left, or right or in place and not diagonal
        if coords.dst not in adj_coords and coords.src != coords.dst:

            return False

        # Player cannot pick up unit at src if unit is None
        if unit is None:
            return False
        # If unit at src is not None, user can only pick up units belong to them
        elif unit.player == self.next_player:
            # if unit at src is Attacker's:
            if unit.player is Player.Attacker:
                # Check if the unit type is AI, firewall, and program, then it can only move up or left by 1 block
                if (unit.type is UnitType.AI or unit.type is UnitType.Firewall or unit.type is UnitType.Program):
                    if (coords.dst.row > coords.src.row or coords.dst.col > coords.src.col or
                            coords.dst.row < coords.src.row - 1 or coords.dst.col < coords.src.col - 1):
                        return False
                    else:
                        # Check if there are any adversarial units adjacent. If yes, AI, F and P cannot move - V and T can move freely.
                        scan_adjacent = []
                        for coordinate in adj_coords:
                            if self.get(coordinate) == None:
                                scan_adjacent.append("")
                            elif self.get(coordinate).to_string()[:1] == "d":
                                scan_adjacent.append("d")
                            else:
                                scan_adjacent.append("a")

                        if "d" in scan_adjacent:
                            if self.get(coords.dst) is None:
                                return False
                            else:
                                return True
                        else:
                            return True  # return True since self-destruction is allowed
                else:
                    # If the unit type is V or T, it can only move to adjacent dst
                    # If dst is empty, unit can move
                    # If dst is occupied, it can also move, but the move is counted as repair or attack
                    return (coords.dst in adj_coords or coords.dst == coords.src)

                    # If dst is occupied, it can also move, but the move is counted as repair or attack or self-destruct
                    return True


            # if unit at src is Defender's:
            if unit.player is Player.Defender:
                # Check if unit type is AI, firewall, and program, it can only move down or right by 1 block
                if (unit.type is UnitType.AI or unit.type is UnitType.Firewall or unit.type is UnitType.Program):
                    if (coords.dst.row < coords.src.row or coords.dst.col < coords.src.col or
                            coords.dst.row > coords.src.row + 1 or coords.dst.col > coords.src.col + 1):
                        return False
                    else:
                        # Check if there are any adversarial units adjacent. If yes, AI, F and P cannot move - V and
                        # T can move freely.
                        scan_adjacent = []
                        for coordinate in adj_coords:
                            if self.get(coordinate) == None:
                                scan_adjacent.append("")
                            elif self.get(coordinate).to_string()[:1] == "d":
                                scan_adjacent.append("d")
                            else:
                                scan_adjacent.append("a")

                        if "a" in scan_adjacent:
                            if self.get(coords.dst) is None:
                                return False
                            else:
                                return True
                        else:
                            return True  # return True since self-destruction is allowed
                else:
                    # If the unit type is V or T, it can only move to adjacent dst
                    # If dst is empty, it can move

                    # If dst is occupied, it can move but the move count as repair or attack
                    return (coords.dst in adj_coords or coords.dst == coords.src)

                    # If dst is occupied, it can move but the move count as repair or attack or self-destruct
                    return True

        # If unit at src is not None & user cannot pick up units that does not belong to them
        else:
            return False

    def perform_move(self, coords: CoordPair) -> Tuple[bool, str]:
        """Validate and perform a move expressed as a CoordPair."""

        row_src = coords.src.row_string()
        row_dst = coords.dst.row_string()

        if self.is_valid_move(coords):

            unit_S = self.get(coords.src)
            unit_T = self.get(coords.dst)

            # ordinary move:
            if unit_T is None:
                self.set(coords.dst, self.get(coords.src))
                self.set(coords.src, None)
                return True, ("move from {}{} to {}{}".format(row_src, coords.src.col, row_dst, coords.dst.col))
            # self-destruct OR repair
            elif unit_S.player == unit_T.player:
                # self-destruct
                # 1. Check if the src = dst
                # 3. Set unit's health = 0 and remove unit from board
                # 4. Define the impacted_range and inflict damage to all unit in impacted_range
                if coords.src == coords.dst:
                    total_dmg = 0
                    unit_S.health = 0
                    self.remove_dead(coords.src)
                    impacted_range = list(coords.src.iter_range(1))
                    for coordinate in impacted_range:
                        if self.get(coordinate) is None:
                            continue
                        else:
                            self.get(coordinate).mod_health(-2)
                            total_dmg += 2
                            self.remove_dead(coordinate)
                    return (True,
                            "self-destruct at {}{}\nself-destructed for {} total damage".format(row_src, coords.src.col,
                                                                                                total_dmg))
                # repair
                # 1. If T's health is already 9, Return false, "invalid move" -> retry
                # 2. Find repair amount from table and add repair unit_T
                else:
                    if unit_T.health < 9:
                        repair_amt = unit_S.repair_amount(unit_T)
                        if repair_amt > 0:
                            unit_T.mod_health(repair_amt)
                            return (True,
                                    "repair from {}{} to {}{}\nrepaired {} health points".format(row_src,
                                                                                                 coords.src.col,
                                                                                                 row_dst,
                                                                                                 coords.dst.col,
                                                                                                 repair_amt))
                        else:
                            return (False, "invalid move")
                    else:
                        return (False, "invalid move")
            # attack
            # 1. Find damage amount inflicted by each unit
            # 2. Perfom bi-directional attack on both units
            # 3. After attack, if any unit's health <= 0, remove it from table
            else:
                damage_amt_T = unit_S.damage_amount(unit_T)
                damage_amt_S = unit_T.damage_amount(unit_S)
                unit_T.mod_health(-damage_amt_T)
                self.remove_dead(coords.dst)
                unit_S.mod_health(-damage_amt_S)
                self.remove_dead(coords.src)
                return (True, "attack from {}{} to {}{}\ncombat damage: to source = {}, to target = {}".format(row_src,
                                                                                                               coords.src.col,
                                                                                                               row_dst,
                                                                                                               coords.dst.col,
                                                                                                               damage_amt_S,
                                                                                                               damage_amt_T))
        else:
            return (False, "invalid move")

    def next_turn(self):
        """Transitions game to the next turn."""
        self.next_player = self.next_player.next()
        self.turns_played += 1

    def to_string(self) -> str:
        """Pretty text representation of the game."""
        dim = self.options.dim
        output = ""
        output += f"Next player: {self.next_player.name}\n"
        output += f"Turns played: {self.turns_played}\n"
        # Added another output line for current the turn number
        output += f"Turn #{self.turns_played + 1}\n"
        coord = Coord()
        output += "\n   "
        for col in range(dim):
            coord.col = col
            label = coord.col_string()
            output += f"{label:^3} "
        output += "\n"
        for row in range(dim):
            coord.row = row
            label = coord.row_string()
            output += f"{label}: "
            for col in range(dim):
                coord.col = col
                unit = self.get(coord)
                if unit is None:
                    output += " .  "
                else:
                    output += f"{str(unit):^3} "
            output += "\n"
        return output

    def __str__(self) -> str:
        """Default string representation of a game."""
        return self.to_string()

    def is_valid_coord(self, coord: Coord) -> bool:
        """Check if a Coord is valid within out board dimensions."""
        dim = self.options.dim
        if coord.row < 0 or coord.row >= dim or coord.col < 0 or coord.col >= dim:
            return False
        return True

    def read_move(self) -> CoordPair:
        """Read a move from keyboard and return as a CoordPair."""
        while True:
            s = input(F'Player {self.next_player.name}, enter your move: ')
            coords = CoordPair.from_string(s)
            if coords is not None and self.is_valid_coord(coords.src) and self.is_valid_coord(coords.dst):
                return coords
            else:
                print('Invalid coordinates! Try again.')

    # Made this return a string now
    def human_turn(self) -> str:
        """Human player plays a move (or get via broker)."""
        output = ""
        if self.options.broker is not None:
            print("Getting next move with auto-retry from game broker...")
            output += "Getting next move with auto-retry from game broker..."
            while True:
                mv = self.get_move_from_broker()
                if mv is not None:
                    (success, result) = self.perform_move(mv)
                    print(f"Broker {self.next_player.name}: ", end='')
                    output += f"Broker {self.next_player.name}: "
                    print(result)
                    output += result
                    if success:
                        self.next_turn()
                        return output
                sleep(0.1)
        else:
            while True:
                mv = self.read_move()
                (success, result) = self.perform_move(mv)
                if success:
                    print(f"Player {self.next_player.name}: ", end='')
                    output += f"Player {self.next_player.name}: "
                    print(result)
                    output += result
                    self.next_turn()
                    return output
                else:
                    print("The move is not valid! Try again.")
                    return "The move is not valid! Try again."

        return potential_attack

    def computer_turn(self, is_minimax) -> [CoordPair, str] | None:
        """Computer plays a move."""
        (mv, output) = self.suggest_move(is_minimax)
        file_output = output
        if mv is not None:
            (success, result) = self.perform_move(mv)
            if success:
                print(f"Computer {self.next_player.name}: ", end='')
                file_output += f"Computer {self.next_player.name}: "
                print(result)
                file_output += result
                self.next_turn()
        return (mv, file_output)

    def player_units(self, player: Player) -> Iterable[Tuple[Coord, Unit]]:
        """Iterates over all units belonging to a player."""
        for coord in CoordPair.from_dim(self.options.dim).iter_rectangle():
            unit = self.get(coord)
            if unit is not None and unit.player == player:
                yield (coord, unit)

    def is_finished(self) -> bool:
        """Check if the game is over."""
        return self.has_winner() is not None

    def has_winner(self) -> Player | None:
        """Check if the game is over and returns winner"""
        if self.options.max_turns is not None and self.turns_played >= self.options.max_turns:
            return Player.Defender
        if self._attacker_has_ai:
            if self._defender_has_ai:
                return None
            else:
                return Player.Attacker
        return Player.Defender

    def move_candidates(self) -> Iterable[CoordPair]:
        """Generate valid move candidates for the next player."""
        move = CoordPair()
        for (src, _) in self.player_units(self.next_player):
            move.src = src
            for dst in src.iter_adjacent():
                move.dst = dst
                if self.is_valid_move(move):
                    yield move.clone()
            move.dst = src
            yield move.clone()

    def suggest_move(self, is_minimax) -> Tuple[CoordPair, str] | None:
        """TODO: Adding minimax alpha beta"""
        global num_evals_per_depth
        """Suggest the next move using minimax alpha beta."""
        output = ""
        start_time = time.time()

        if(is_minimax):
            print("Minimax")
            (score, move, depth) = minimax(self, 1, self.next_player is Player.Attacker)
        else:
            print("Alpha-Beta")
            (score, move, depth) = alphabeta(self, 1, float('-inf'), float('inf'), self.next_player is Player.Attacker)
        self.stats.evaluations_per_depth[depth] = num_evals_per_depth

        elapsed_seconds = (time.time() - start_time)
        self.stats.total_seconds += elapsed_seconds
        print(f"Heuristic score: {score}")
        output += f"Heuristic score: {score}"

        print(f"Evals per depth: ", end='')
        output += f"Evals per depth: "
        for k in sorted(self.stats.evaluations_per_depth.keys()):
            print(f"{k}:{self.stats.evaluations_per_depth[k]} ", end='')
            output += f"{k}:{self.stats.evaluations_per_depth[k]}\n"
        print()
        total_evals = sum(self.stats.evaluations_per_depth.values())
        print(f"Cumulative evals: {total_evals}")
        output += f"Cumulative evals: {total_evals}"

        print(f"Cumulative % evals by depth: ", end='')
        output += f"Cumulative % evals by depth: "
        for j in sorted(self.stats.evaluations_per_depth.keys()):
            print(f"{j}:{self.stats.evaluations_per_depth[j] / total_evals * 100}%", end='')
            output += f"{j}:{self.stats.evaluations_per_depth[j] / total_evals * 100} "
        print()

        if self.stats.total_seconds > 0:
            print(f"Eval perf.: {total_evals / elapsed_seconds / 1000:0.6f}k/s")
            output += f"Eval perf.: {total_evals / self.stats.total_seconds / 1000:0.6f}k/s"
        print(f"Elapsed time: {(elapsed_seconds):0.6f}s")
        output += f"Elapsed time: {(elapsed_seconds):0.6f}s"
        return (move, output)

    def post_move_to_broker(self, move: CoordPair):
        """Send a move to the game broker."""
        if self.options.broker is None:
            return
        data = {
            "from": {"row": move.src.row, "col": move.src.col},
            "to": {"row": move.dst.row, "col": move.dst.col},
            "turn": self.turns_played
        }
        try:
            r = requests.post(self.options.broker, json=data)
            if r.status_code == 200 and r.json()['success'] and r.json()['data'] == data:
                # print(f"Sent move to broker: {move}")
                pass
            else:
                print(f"Broker error: status code: {r.status_code}, response: {r.json()}")
        except Exception as error:
            print(f"Broker error: {error}")

    def get_move_from_broker(self) -> CoordPair | None:
        """Get a move from the game broker."""
        if self.options.broker is None:
            return None
        headers = {'Accept': 'application/json'}
        try:
            r = requests.get(self.options.broker, headers=headers)
            # If the status code is 200 and the JSOn response data is success
            if r.status_code == 200 and r.json()['success']:
                data = r.json()['data']  # parse the data
                if data is not None:
                    if data['turn'] == self.turns_played + 1:
                        # Extract the move
                        move = CoordPair(
                            Coord(data['from']['row'], data['from']['col']),
                            Coord(data['to']['row'], data['to']['col'])
                        )
                        print(f"Got move from broker: {move}")
                        return move
                    else:
                        # print("Got broker data for wrong turn.")
                        # print(f"Wanted {self.turns_played+1}, got {data['turn']}")
                        pass
                else:
                    # print("Got no data from broker")
                    pass
            else:
                print(f"Broker error: status code: {r.status_code}, response: {r.json()}")
        except Exception as error:
            print(f"Broker error: {error}")
        return None


##############################################################################################################

def main():
    # parse command line arguments
    parser = argparse.ArgumentParser(
        prog='ai_wargame',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--max_depth', type=int, help='maximum search depth')
    parser.add_argument('--max_time', type=float, help='maximum search time')
    parser.add_argument('--game_type', type=str, default="manual", help='game type: auto|attacker|defender|manual')
    # To customize adversarial search type: minimax OR alpha-beta
    parser.add_argument('--not_alpha_beta', action='store_false',
                        help='adversarial search type: minimax(FALSE)|alpha_beta(TRUE)')  # action="store_true" means is that if the argument is given on the command line then a True value should be stored in the parser.
    # To customize max number of turn
    parser.add_argument('--max_turns', type=int, default=100, help='max number of turns')

    parser.add_argument('--broker', type=str, help='play via a game broker')
    args = parser.parse_args()

    # parse the game type
    if args.game_type == "attacker":
        game_type = GameType.AttackerVsComp
    elif args.game_type == "defender":
        game_type = GameType.CompVsDefender
    elif args.game_type == "manual":
        game_type = GameType.AttackerVsDefender
    else:
        game_type = GameType.CompVsComp

    # set up game options
    options = Options(game_type=game_type)

    # override class defaults via command line options
    if args.max_depth is not None:
        options.max_depth = args.max_depth
    if args.max_time is not None:
        options.max_time = args.max_time
    if args.not_alpha_beta is not None:
        options.alpha_beta = args.not_alpha_beta
    if args.max_turns is not None:
        options.max_turns = args.max_turns
    if args.broker is not None:
        options.broker = args.broker

    # create a new game
    game = Game(options=options)

    print(f"Max depth: {options.max_depth}")
    print(f"Max time (seconds): {options.max_time}")
    print(f"Maximum number of turns: {options.max_turns}")
    print(f"Alpha-Beta: {options.alpha_beta}")
    print(f"Play mode: {game.options.game_type}")
    print(f"Heuristic: e0")

    f = open("gameTrace-{}-{}-{}.txt".format(options.alpha_beta, options.max_time, options.max_turns), "w")
    print(f"Max depth: {options.max_depth}", file=f)
    print(f"Max time (seconds): {options.max_time}", file=f)
    print(f"Maximum number of turns: {options.max_turns}", file=f)
    print(f"Alpha-Beta: {options.alpha_beta}", file=f)
    print(f"Play mode: {game.options.game_type}", file=f)
    print(f"Heuristic: e0\n", file=f)

    # the main game loop
    while True:
        print("\n")
        print(game)
        print(game, file=f)

        winner = game.has_winner()
        if winner is not None:
            print(f"{winner.name} wins in {game.turns_played} turns!")
            print(f"{winner.name} wins in {game.turns_played} turns!", file=f)
            break
        if game.options.game_type == GameType.AttackerVsDefender:
            result = game.human_turn()
            print(f"{result}\n", file=f)
        elif game.options.game_type == GameType.AttackerVsComp and game.next_player == Player.Attacker:
            result = game.human_turn()
            print(f"{result}\n", file=f)
        elif game.options.game_type == GameType.CompVsDefender and game.next_player == Player.Defender:
            result = game.human_turn()
            print(f"{result}\n", file=f)
        else:
            player = game.next_player
            (move, result) = game.computer_turn(not args.not_alpha_beta)
            print(f"{result}\n", file=f)
            if move is not None:
                game.post_move_to_broker(move)
            else:
                print("Computer doesn't know what to do!!!")
                print("Computer doesn't know what to do!!!", file=f)
                exit(1)

    f.close()


##############################################################################################################

if __name__ == '__main__':
    main()
