import copy
import json
import os
import time
import urllib.request
from typing import Any, Dict, List, Tuple, Union

import numpy as np
from scipy.optimize import linprog

global penguin_url, headers
penguin_url = "https://penguin-stats.io/PenguinStats/api/"
headers = {"User-Agent": "ArkPlanner"}

gamedata_langs = ["en_US", "ja_JP", "ko_KR", "zh_CN"]
DEFAULT_LANG = "en_US"
NON_CN_WORLD_NUM = 4
FILTER_FREQ_DEFAULT = 100


class MaterialPlanning(object):
    def __init__(
        self,
        filter_freq=FILTER_FREQ_DEFAULT,
        filter_stages=[],
        url_stats="result/matrix?show_stage_details=true&show_item_details=true",
        url_rules="formula",
        path_stats="data/matrix.json",
        dont_save_data=False,
        path_rules="data/formula.json",
        gamedata_path="https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData/"
        + "master/{}/gamedata/excel/item_table.json",
    ):
        """
        Object initialization.
        Args:
            filter_freq: int or None. The lowest frequency that we consider.
                No filter will be applied if None.
            url_stats: string. url to the dropping rate stats data.
            url_rules: string. url to the composing rules data.
            path_stats: string. local path to the dropping rate stats data.
            path_rules: string. local path to the composing rules data.
        """
        if not dont_save_data:
            try:
                material_probs, convertion_rules = load_data(path_stats, path_rules)
            except FileNotFoundError:
                material_probs, convertion_rules = request_data(
                    penguin_url + url_stats,
                    penguin_url + url_rules,
                    path_stats,
                    path_rules,
                    gamedata_path,
                )
                print("done.")
        else:
            material_probs, convertion_rules = request_data(
                penguin_url + url_stats,
                penguin_url + url_rules,
                path_stats,
                path_rules,
                gamedata_path,
                dont_save_data,
            )
        self.itemdata = request_itemdata(gamedata_path)
        self.itemdata_rv = {
            lang: {v: k for k, v in dct.items()} for lang, dct in self.itemdata.items()
        }

        filtered_probs = []
        for dct in material_probs["matrix"]:
            if (
                dct["stage"]["apCost"] > 0.1
                and dct["stage"]["code"] not in filter_stages
            ):
                if not filter_freq or dct["times"] >= filter_freq:
                    filtered_probs.append(dct)
        material_probs["matrix"] = filtered_probs

        self._set_lp_parameters(*self._pre_processing(material_probs, convertion_rules))

    def _pre_processing(self, material_probs, convertion_rules):
        """
        Compute costs, convertion rules and items probabilities from requested dictionaries.
        Args:
            material_probs: List of dictionaries recording the dropping info per stage per item.
                Keys of instances: ["itemID", "times", "itemName", "quantity", "apCost", "stageCode", "stageID"].
            convertion_rules: List of dictionaries recording the rules of composing.
                Keys of instances: ["id", "name", "level", "source", "madeof"].
        """
        # To count items and stages.
        additional_items = {"30135": u"D32钢", "30125": u"双极纳米片", "30115": u"聚合剂"}
        exp_unit = 200 * (30.0 - 0.048 * 30) / 7400
        gold_unit = 0.004
        exp_worths = {
            "2001": exp_unit,
            "2002": exp_unit * 2,
            "2003": exp_unit * 5,
            "2004": exp_unit * 10,
            "3003": exp_unit * 2,
        }
        gold_worths = {}

        item_dct = {}
        stage_dct = {}
        for dct in material_probs["matrix"]:
            item_dct[dct["item"]["itemId"]] = dct["item"]["name"]
            stage_dct[dct["stage"]["code"]] = dct["stage"]["code"]
        item_dct.update(additional_items)

        # To construct mapping from id to item names.
        item_array = []
        item_id_array = []
        for k, v in item_dct.items():
            try:
                float(k)
                item_array.append(v)
                item_id_array.append(k)
            except ValueError:
                pass
        self.item_array = np.array(item_array)
        self.item_id_array = np.array(item_id_array)
        self.item_id_rv = {int(v): k for k, v in enumerate(item_id_array)}
        self.item_dct_rv = {v: k for k, v in enumerate(item_array)}

        # To construct mapping from stage id to stage names and vice versa.
        stage_array = []
        for k, v in stage_dct.items():
            stage_array.append(v)
        self.stage_array = np.array(stage_array)
        self.stage_dct_rv = {v: k for k, v in enumerate(self.stage_array)}

        # To format dropping records into sparse probability matrix
        probs_matrix = np.zeros([len(stage_array), len(item_array)])
        cost_lst = np.zeros(len(stage_array))
        cost_exp_offset = np.zeros(len(stage_array))
        cost_gold_offset = np.zeros(len(stage_array))
        for dct in material_probs["matrix"]:
            try:
                cost_lst[self.stage_dct_rv[dct["stage"]["code"]]] = dct["stage"][
                    "apCost"
                ]
                float(dct["item"]["itemId"])
                probs_matrix[
                    self.stage_dct_rv[dct["stage"]["code"]],
                    self.item_dct_rv[dct["item"]["name"]],
                ] = dct["quantity"] / float(dct["times"])
                if cost_lst[self.stage_dct_rv[dct["stage"]["code"]]] != 0:
                    cost_gold_offset[self.stage_dct_rv[dct["stage"]["code"]]] = -dct[
                        "stage"
                    ]["apCost"] * (12 * gold_unit)
            except ValueError:
                pass

            try:
                cost_exp_offset[self.stage_dct_rv[dct["stage"]["code"]]] -= (
                    exp_worths[dct["item"]["itemId"]]
                    * dct["quantity"]
                    / float(dct["times"])
                )
            except (KeyError, ValueError):
                pass

            try:
                cost_gold_offset[self.stage_dct_rv[dct["stage"]["code"]]] -= (
                    gold_worths[dct["item"]["itemId"]]
                    * dct["quantity"]
                    / float(dct["times"])
                )
            except (KeyError, ValueError):
                pass

        # Hardcoding: extra gold farmed.
        cost_gold_offset[self.stage_dct_rv["S4-6"]] -= 3228 * gold_unit
        cost_gold_offset[self.stage_dct_rv["S5-2"]] -= 2484 * gold_unit

        # To build equivalence relationship from convert_rule_dct.
        self.convertions_dct = {}
        convertion_matrix = []
        convertion_outc_matrix = []
        convertion_cost_lst = []
        for rule in convertion_rules:
            convertion = np.zeros(len(self.item_array))
            convertion[self.item_dct_rv[rule["name"]]] = 1

            comp_dct = {comp["id"]: comp["count"] for comp in rule["costs"]}
            self.convertions_dct[rule["id"]] = comp_dct
            for item_id in comp_dct:
                convertion[self.item_id_rv[int(item_id)]] -= comp_dct[item_id]
            convertion_matrix.append(copy.deepcopy(convertion))

            outc_dct = {outc["name"]: outc["count"] for outc in rule["extraOutcome"]}
            outc_wgh = {outc["name"]: outc["weight"] for outc in rule["extraOutcome"]}
            weight_sum = float(sum(outc_wgh.values()))
            for item_id in outc_dct:
                convertion[self.item_dct_rv[item_id]] += (
                    outc_dct[item_id] * 0.175 * outc_wgh[item_id] / weight_sum
                )
            convertion_outc_matrix.append(convertion)

            convertion_cost_lst.append(rule["goldCost"] * 0.004)

        convertions_group = (
            np.array(convertion_matrix),
            np.array(convertion_outc_matrix),
            np.array(convertion_cost_lst),
        )
        farms_group = (probs_matrix, cost_lst, cost_exp_offset, cost_gold_offset)

        return convertions_group, farms_group

    def _set_lp_parameters(self, convertions_group, farms_group):
        """
        Object initialization.
        Args:
            convertion_matrix: matrix of shape [n_rules, n_items].
                Each row represent a rule.
            convertion_cost_lst: list. Cost in equal value to the currency spent in convertion.
            probs_matrix: sparse matrix of shape [n_stages, n_items].
                Items per clear (probabilities) at each stage.
            cost_lst: list. Costs per clear at each stage.
        """
        (
            self.convertion_matrix,
            self.convertion_outc_matrix,
            self.convertion_cost_lst,
        ) = convertions_group
        (
            self.probs_matrix,
            self.cost_lst,
            self.cost_exp_offset,
            self.cost_gold_offset,
        ) = farms_group

        assert len(self.probs_matrix) == len(self.cost_lst)
        assert len(self.convertion_matrix) == len(self.convertion_cost_lst)
        assert self.probs_matrix.shape[1] == self.convertion_matrix.shape[1]

    def update(
        self,
        filter_freq=FILTER_FREQ_DEFAULT,
        filter_stages=None,
        url_stats="result/matrix?show_stage_details=true&show_item_details=true",
        url_rules="formula",
        path_stats="data/matrix.json",
        path_rules="data/formula.json",
        gamedata_path="https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData/master/{}/gamedata/excel/item_table.json",
        dont_save_data=False,
    ):
        """
        To update parameters when probabilities change or new items added.
        Args:
            url_stats: string. url to the dropping rate stats data.
            url_rules: string. url to the composing rules data.
            path_stats: string. local path to the dropping rate stats data.
            path_rules: string. local path to the composing rules data.
        """
        material_probs, convertion_rules = request_data(
            penguin_url + url_stats,
            penguin_url + url_rules,
            path_stats,
            path_rules,
            gamedata_path,
            dont_save_data,
        )
        self.itemdata = request_itemdata(gamedata_path)
        self.itemdata_rv = {
            lang: {v: k for k, v in dct.items()} for lang, dct in self.itemdata.items()
        }

        if filter_freq:
            if filter_stages is None:
                filter_stages = []
            filtered_probs = []
            for dct in material_probs["matrix"]:
                if (
                    dct["times"] >= filter_freq
                    and dct["stage"]["code"] not in filter_stages
                ):
                    filtered_probs.append(dct)
            material_probs["matrix"] = filtered_probs

        self._set_lp_parameters(*self._pre_processing(material_probs, convertion_rules))

    def _get_plan_no_prioties(
        self, demand_lst, outcome=False, gold_demand=True, exp_demand=True
    ):
        """
        To solve linear programming problem without prioties.
        Args:
            demand_lst: list of materials demand. Should include all items (zero if not required).
        Returns:
            strategy: list of required clear times for each stage.
            fun: estimated total cost.
        """
        A_ub = (
            np.vstack([self.probs_matrix, self.convertion_outc_matrix])
            if outcome
            else np.vstack([self.probs_matrix, self.convertion_matrix])
        ).T
        farm_cost = (
            self.cost_lst
            + (self.cost_exp_offset if exp_demand else 0)
            + (self.cost_gold_offset if gold_demand else 0)
        )
        convertion_cost_lst = (
            self.convertion_cost_lst
            if gold_demand
            else np.zeros(self.convertion_cost_lst.shape)
        )
        cost = np.hstack([farm_cost, convertion_cost_lst])
        assert np.any(farm_cost >= 0)

        excp_factor = 1.0
        dual_factor = 1.0

        solution = None
        for _ in range(5):
            solution = linprog(
                c=cost,
                A_ub=-A_ub,
                b_ub=-np.array(demand_lst) * excp_factor,
                method="interior-point",
            )
            if solution.status != 4:
                break

            excp_factor /= 10.0

        dual_solution = None
        for _ in range(5):
            dual_solution = linprog(
                c=-np.array(demand_lst) * excp_factor * dual_factor,
                A_ub=A_ub.T,
                b_ub=cost,
                method="interior-point",
            )
            if dual_solution.status != 4:
                break

            dual_factor /= 10.0

        return solution, dual_solution, excp_factor

    def convert_requirements(
        self, requirement_dct: Union[None, Dict[str, int]]
    ) -> Tuple[Dict[int, int], str]:
        """
        Converts a requirement dict with variable keys into a dict mapping an
        item's ID to its quantity.
        Args:
            requirement_dct: a Dict[str, int] where the item keys are one of the
                follow types: English name, Chinese name, Japanese name, Korean name,
                or item ID.
        Returns:
            requirements: a Dict[int, int]
            lang: the language successfully parsed language or "id"
        Raises:
            A BaseException initialized with all the KeyErrors that occured during
            execution if the function was unable to parse the input dict.
        """
        if requirement_dct is None:
            return {}, ""
        err_lst: List[BaseException] = []
        # Try parsing as IDs
        try:
            ret = {}
            for k, v in requirement_dct.items():
                ret[int(k)] = int(v)
            return ret, "id"
        except (ValueError, KeyError) as err:
            err_lst.append(err)
        # Try parsing as each lang
        for lang, nameMap in self.itemdata_rv.items():
            ret = {}
            try:
                for k, v in requirement_dct.items():
                    ret[nameMap[k]] = int(v)
                return ret, lang
            except (ValueError, KeyError) as err:
                err_lst.append(err)
        # TODO: create custom exception class
        raise BaseException(err_lst)

    def get_plan(
        self,
        requirement_dct,
        deposited_dct=None,
        print_output=True,
        outcome=False,
        gold_demand=True,
        exp_demand=True,
        language=None,
        exclude=None,
        non_cn_compat=False,
    ):
        """
        User API. Computing the material plan given requirements and owned items.
        Args:
                requirement_dct: dictionary. Contain only required items with their numbers.
                deposit_dct: dictionary. Contain only owned items with their numbers.
        """
        status_dct = {
            0: "Optimization terminated successfully. ",
            1: "Iteration limit reached. ",
            2: "Problem appears to be infeasible. ",
            3: "Problem appears to be unbounded. ",
            4: "Numerical difficulties encountered.",
        }
        stt = time.time()
        requirement_dct, requirement_lang = self.convert_requirements(requirement_dct)
        if language is None:
            language = requirement_lang
        deposited_dct, _ = self.convert_requirements(None)

        demand_lst = [0 for x in range(len(self.item_array))]
        for k, v in requirement_dct.items():
            demand_lst[self.item_id_rv[k]] = v
        for k, v in deposited_dct.items():
            demand_lst[self.item_dct_rv[k]] -= v

        if exclude is None:
            exclude = set()
        else:
            exclude = set(exclude)

        is_stage_alive = []
        for stage in self.stage_array:
            if stage in exclude:
                is_stage_alive.append(False)
                continue
            if non_cn_compat:
                try:
                    if int(stage.lstrip("S")[0]) > NON_CN_WORLD_NUM:
                        is_stage_alive.append(False)
                        continue
                except ValueError:
                    pass
            is_stage_alive.append(True)

        if exclude or non_cn_compat:
            BackTrace = [
                copy.copy(self.stage_array),
                copy.copy(self.cost_lst),
                copy.copy(self.probs_matrix),
                copy.copy(self.cost_exp_offset),
                copy.copy(self.cost_gold_offset),
            ]
            self.stage_array = self.stage_array[is_stage_alive]
            self.cost_lst = self.cost_lst[is_stage_alive]
            self.probs_matrix = self.probs_matrix[is_stage_alive]
            self.cost_exp_offset = self.cost_exp_offset[is_stage_alive]
            self.cost_gold_offset = self.cost_gold_offset[is_stage_alive]

        solution, dual_solution, excp_factor = self._get_plan_no_prioties(
            demand_lst, outcome, gold_demand, exp_demand
        )
        x, status = solution.x / excp_factor, solution.status
        y = dual_solution.x
        n_looting, n_convertion = x[: len(self.cost_lst)], x[len(self.cost_lst) :]

        cost = np.dot(x[: len(self.cost_lst)], self.cost_lst)
        gcost = np.dot(x[len(self.cost_lst) :], self.convertion_cost_lst) / 0.004
        gold = -np.dot(n_looting, self.cost_gold_offset) / 0.004
        exp = -np.dot(n_looting, self.cost_exp_offset) * 7400 / 30.0

        if status != 0:
            raise ValueError(status_dct[status])

        stages = []
        for i, t in enumerate(n_looting):
            if t >= 0.1:
                target_items = np.where(self.probs_matrix[i] >= 0.02)[0]
                items = {}
                for idx in target_items:
                    if len(self.item_id_array[idx]) != 5:
                        continue
                    try:
                        name_str = self.itemdata[language][int(self.item_id_array[idx])]
                    except KeyError:
                        # Fallback to CN if language is unavailable
                        name_str = self.itemdata["zh_CN"][int(self.item_id_array[idx])]
                    items[name_str] = float2str(self.probs_matrix[i, idx] * t)
                stage = {
                    "stage": self.stage_array[i],
                    "count": float2str(t),
                    "items": items,
                }
                stages.append(stage)

        crafts = []
        for i, t in enumerate(n_convertion):
            if t >= 0.1:
                idx = np.argmax(self.convertion_matrix[i])
                item_id = self.item_id_array[idx]
                try:
                    target_id = self.itemdata[language][int(item_id)]
                except KeyError:
                    target_id = self.itemdata["zh_CN"][int(item_id)]
                materials = {}
                for k, v in self.convertions_dct[item_id].items():
                    try:
                        key_name = self.itemdata[language][int(k)]
                    except KeyError:
                        key_name = self.itemdata["zh_CN"][int(k)]
                    materials[key_name] = str(v * int(t + 0.9))
                synthesis = {
                    "target": target_id,
                    "count": str(int(t + 0.9)),
                    "materials": materials,
                }
                crafts.append(synthesis)
            elif t >= 0.05:
                idx = np.argmax(self.convertion_matrix[i])
                item_id = self.item_id_array[idx]
                try:
                    target_name = self.itemdata[language][int(item_id)]
                except KeyError:
                    target_name = self.itemdata["zh_CN"][int(item_id)]
                materials = {}
                for k, v in self.convertions_dct[item_id].items():
                    try:
                        key_name = self.itemdata[language][int(k)]
                    except KeyError:
                        key_name = self.itemdata["zh_CN"][int(k)]
                    materials[key_name] = "%.1f" % (v * t)
                synthesis = {
                    "target": target_name,
                    "count": "%.1f" % t,
                    "materials": materials,
                }
                crafts.append(synthesis)

        values = [
            {"level": "1", "items": []},
            {"level": "2", "items": []},
            {"level": "3", "items": []},
            {"level": "4", "items": []},
            {"level": "5", "items": []},
        ]
        for i, item_id in enumerate(self.item_id_array):
            if len(item_id) == 5 and y[i] > 0.1:
                try:
                    item_name = self.itemdata[language][int(item_id)]
                except KeyError:
                    item_name = self.itemdata["zh_CN"][int(item_id)]
                item_value = {"name": item_name, "value": "%.2f" % y[i]}
                values[int(self.item_id_array[i][-1]) - 1]["items"].append(item_value)
        for group in values:
            group["items"] = sorted(
                group["items"], key=lambda k: float(k["value"]), reverse=True
            )

        res = {
            "lang": language,
            "cost": int(cost),
            "gcost": int(gcost),
            "gold": int(gold),
            "exp": int(exp),
            "stages": stages,
            "craft": crafts,
            "values": list(reversed(values)),
        }

        if print_output:
            print(
                status_dct[status]
                + (" Computed in %.4f seconds," % (time.time() - stt))
            )

        if print_output:
            print(
                "Estimated total cost: %d, gold: %d, exp: %d."
                % (res["cost"], res["gold"], res["exp"])
            )
            print("Loot at following stages:")
            for stage in stages:
                display_lst = [k + "(%s) " % stage["items"][k] for k in stage["items"]]
                print(
                    "Stage "
                    + stage["stage"]
                    + "(%s times) ===> " % stage["count"]
                    + ", ".join(display_lst)
                )

            print("\nSynthesize following items:")
            for synthesis in crafts:
                display_lst = [
                    k + "(%s) " % synthesis["materials"][k]
                    for k in synthesis["materials"]
                ]
                print(
                    synthesis["target"]
                    + "(%s) <=== " % synthesis["count"]
                    + ", ".join(display_lst)
                )

            print("\nItems Values:")
            for i, group in reversed(list(enumerate(values))):
                display_lst = [
                    "%s:%s" % (item["name"], item["value"]) for item in group["items"]
                ]
                print("Level %d items: " % (i + 1))
                print(", ".join(display_lst))

        if exclude:
            self.stage_array = BackTrace[0]
            self.cost_lst = BackTrace[1]
            self.probs_matrix = BackTrace[2]
            self.cost_exp_offset = BackTrace[3]
            self.cost_gold_offset = BackTrace[4]

        return res


def float2str(x: float, offset=0.5):
    if x < 1.0:
        out = "%.1f" % x
    else:
        out = "%d" % (int(x + offset))
    return out


def request_data(
    url_stats,
    url_rules,
    save_path_stats,
    save_path_rules,
    gamedata_path,
    dont_save_data=False,
) -> Tuple[Any, Any]:
    """
    To request probability and convertion rules from web resources and store at local.
    Args:
        url_stats: string. url to the dropping rate stats data.
        url_rules: string. url to the composing rules data.
        save_path_stats: string. local path for storing the stats data.
        save_path_rules: string. local path for storing the composing rules data.
    Returns:
        material_probs: dictionary. Content of the stats json file.
        convertion_rules: dictionary. Content of the rules json file.
    """
    if not dont_save_data:
        try:
            os.mkdir(os.path.dirname(save_path_stats))
        except FileExistsError:
            pass
        try:
            os.mkdir(os.path.dirname(save_path_rules))
        except FileExistsError:
            pass

    # TODO: async requests
    req = urllib.request.Request(url_stats, None, headers)
    with urllib.request.urlopen(req) as response:
        material_probs = json.loads(response.read().decode())
        if not dont_save_data:
            with open(save_path_stats, "w") as outfile:
                json.dump(material_probs, outfile)

    req = urllib.request.Request(url_rules, None, headers)
    with urllib.request.urlopen(req) as response:
        response = urllib.request.urlopen(req)
        convertion_rules = json.loads(response.read().decode())
        if not dont_save_data:
            with open(save_path_rules, "w") as outfile:
                json.dump(convertion_rules, outfile)

    return material_probs, convertion_rules


def request_itemdata(gamedata_path: str) -> Dict[str, Dict[int, str]]:
    """
    Pulls item data github sources.
    Args:
        gamedata_path: a format string that takes in 1 argument to format in the region name.
    Returns:
        itemdata: a dict mapping a region's name to a dict mapping an item ID to its name.
    """
    itemdata = {}
    for lang in gamedata_langs:
        req = urllib.request.Request(gamedata_path.format(lang), None, headers)
        with urllib.request.urlopen(req) as response:
            response = urllib.request.urlopen(req)
            # filter out unneeded data, we only care about ones with purely numerical IDs
            data = {}
            for k, v in json.loads(response.read().decode())["items"].items():
                try:
                    i = int(k)
                except ValueError:
                    continue
                data[i] = v["name"]
            itemdata[lang] = data

    return itemdata


def load_data(path_stats, path_rules):
    """
    To load stats and rules data from local directories.
    Args:
        path_stats: string. local path to the stats data.
        path_rules: string. local path to the composing rules data.
    Returns:
        material_probs: dictionary. Content of the stats json file.
        convertion_rules: dictionary. Content of the rules json file.
    """
    with open(path_stats) as json_file:
        material_probs = json.load(json_file)
    with open(path_rules) as json_file:
        convertion_rules = json.load(json_file)

    return material_probs, convertion_rules
