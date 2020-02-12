import sys

from MaterialPlanning import MaterialPlanning

if __name__ == "__main__":

    if "-fe" in sys.argv:
        filter_stages = ["GT-" + str(i) for i in range(1, 7)]
    else:
        filter_stages = []

    mp = MaterialPlanning(filter_stages=filter_stages)

    with open("required.txt", "r", encoding="utf-8") as f:
        required_dct = {}
        for line in f.readlines():
            split = line.split(" ")
            required_dct[" ".join(split[:-1])] = int(split[-1])

    with open("owned.txt", "r", encoding="utf-8") as f:
        owned_dct = {}
        for line in f.readlines():
            split = line.split(" ")
            owned_dct[" ".join(split[:-1])] = int(split[-1])

    mp.get_plan(
        required_dct,
        owned_dct,
        True,
        outcome=True,
        gold_demand=False,
        exp_demand=True,
        language="en_US",
    )
