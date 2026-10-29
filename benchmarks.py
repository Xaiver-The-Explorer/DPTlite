"""
benchmarks.py
-------------
A sanity check for the order/disorder predictor and transmembrane helix predictor in biology.py.

Run it from the project folder: python3 benchmarks.py

Each protein below has a well-known behaviour in the lab (folded, or intrinsically disordered). The EXPECTED column was written down BEFORE
the predictor was run on it, so the test can't be quietly bent to fit.

Sequences were typed from UniProt entries. If you ever doubt one, paste it into UniProt's BLAST or compare its length with the accession given.
"""

from biology import predict_order_disorder, predict_transmembrane_helices, BORDERLINE_MARGIN


# ---------------
# Order/disorder
# ---------------

ORDERED = "ordered"
DISORDERED = "disordered"

HEMOGLOBIN_BETA = (  # P68871, 147 aa
    "MVHLTPEEKSAVTALWGKVNVDEVGGEALGRLLVVYPWTQRFFESFGDLSTPDAVMGNPKVKAHGKKVLGAFSDGLAHLDNLKGTFATLSELHCDKLHVDPENFRLLGNVLVCVLAHHFGKEFTPPVQAAYQKVVAGVANALAHKYH"
)
PREPROINSULIN = (  # P01308, 110 aa (signal peptide + B chain + C peptide + A chain)
    "MALWMRLLPLLALLALWGPDPAAAFVNQHLCGSHLVEALYLVCGERGFFYTPKTRREAEDLQVGQVELGGGPGAGSLQPLALEGSLQKRGIVEQCCTSICSLYQLENYCN"
)
P53_FULL = (  # P04637, 393 aa
    "MEEPQSDPSVEPPLSQETFSDLWKLLPENNVLSPLPSQAMDDLMLSPDDIEQWFTEDPGPDEAPRMPEAAPPVAPAPAAPTPAAPAPAPSWPLSSSVPSQKTYQGSYGFRLGFLHSGTAKSVTCTYSPALNKMFCQLAKTCPVQLWVDSTPPPGTRVRAMAIYKQSQHMTEVVRRCPHHERCSDSDGLAPPQHLIRVEGNLRVEYLDDRNTFRHSVVVPYEPPEVGSDCTTIHYNYMCNSSCMGGMNRRPILTIITLEDSSGNLLGRNSFEVRVCACPGRDRRTEEENLRKKGEPHHELPPGSTKRALPNNTSSSPQPKKKPLDGEYFTLQIRGRERFEMFRELNEALELKDAQAGKEPGGSRAHSSHLKSKKGQSTSRHKKLMFKTEGPDSD"
)

# (name, sequence, expected, why we expect it)
BENCHMARKS = [
    ("Hemoglobin beta (P68871)", HEMOGLOBIN_BETA, ORDERED, "classic all-helical globin fold"),
    ("Preproinsulin (P01308)", PREPROINSULIN, ORDERED, "folds, forms disulfide-linked insulin"),
    ("Proinsulin (no signal peptide)", PREPROINSULIN[24:], ORDERED, "folded precursor"),
    ("Ubiquitin (P0CG48 unit)",
     "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG",
     ORDERED, "very stable beta-grasp fold"),
    ("Hen egg-white lysozyme (P00698)",
     "KVFGRCELAAAMKRHGLDNYRGYSLGNWVCAAKFESNFNTQATNRNTDGSTDYGILQINSRWWCNDGRTPGSRNLCNIPCSALLSSDITASVNCAKKIVSDGNGMNAWVAWRNRCKGTDVQAWIRGCRL",
     ORDERED, "textbook globular enzyme"),
    ("p53 DNA-binding core (res. 94-312)", P53_FULL[93:312], ORDERED, "folded, zinc-binding domain"),
    ("Calmodulin (P0DP23)",
     "MADQLTEEQIAEFKEAFSLFDKDGDGTITTKELGTVMRSLGQNPTEAELQDMINEVDADGNGTIDFPEFLTMMARKMKDTDSEEEIREAFRVFDKDGNGYISAAELRHVMTNLGEKLTDEEVDEMIREADIDGDGQVNYEEFVQMMTAK",
     ORDERED, "folded EF-hand protein (but very acidic: a known hard case)"),
    ("p53 N-terminal region (res. 1-93)", P53_FULL[:93], DISORDERED, "transactivation + proline-rich region, unstructured"),
    ("alpha-Synuclein (P37840)",
     "MDVFMKGLSKAKEGVVAAAEKTKQGVAEAAGKTKEGVLYVGSKTKEGVVHGVATVAEKTKEQVTNVGGAVVTGVTAVAQKTVEGAGSIAAATGFVKKDQLGKNEEGAPQEGILEDMPVDPDNEAYEMPSEEGYQDYEPEA",
     DISORDERED, "the textbook natively unfolded protein"),
    ("Prothymosin alpha (P06454)",
     "MSDAAVDTSSEITTKDLKEKKEVVEEAENGRDAPANGNANEENGEQEADNEVDEEEEEGGEEEEEEEEEGDGEEEDGDEDEEAESATGKRAAEDDEDDDVDTKKQKTDEDD",
     DISORDERED, "extremely acidic, natively unfolded"),
]


def main():

    print(f"{'protein':36s} {'aa':>4s} {'<H>':>6s} {'|<R>|':>6s} {'bound.':>7s} {'margin':>7s}  {'predicted':11s} {'expected':11s}  result")
    print("-" * 108)
    correct = wrong = undecided = 0
    for name, seq, expected, _why in BENCHMARKS:
        result = predict_order_disorder(seq)
        verdict = result["verdict"]
        if verdict == "borderline":
            undecided += 1
            outcome = "undecided"
        elif verdict == expected:
            correct += 1
            outcome = "PASS"
        else:
            wrong += 1
            outcome = "FAIL  <--"
        print(f"{name:36s} {len(seq):4d} {result['mean_hydropathy']:6.3f} {result['abs_net_charge']:6.3f} "
              f"{result['boundary']:7.3f} {result['margin']:+7.3f}  {verdict:11s} {expected:11s}  {outcome}")
    print("-" * 108)
    decided = correct + wrong
    print(f"Confident calls: {correct} correct, {wrong} wrong (out of {decided} decided)")
    print(f"Undecided (borderline): {undecided} of {len(BENCHMARKS)}")
    print(f"Borderline band: +/- {BORDERLINE_MARGIN} around the boundary")


# ----------------------
# Transmembrane helices
# ----------------------

# Two membrane proteins whose helices are annotated in UniProt (sequences and helix positions copied from the UniProt entries), plus every
# soluble protein above as a negative control: for those, ANY predicted TM segment is a false alarm.

BACTERIORHODOPSIN = (  # P02945, 262 aa (mass checks out: 28,256 Da)
    "MLELLPTAVEGVSQAQITGRPEWIWLALGTALMGLGTLYFLVKGMGVSDPDAKKFYAITTLVPAIAFTMYLSMLLGYGLTMVPFGGEQNPIYWARYADWLFTTPLLLLDLALLVDADQGTILALVGADGIMIGTGLVGALTKVYSYRFVWWAISTAAMLYILYVLFFGFTSKAESMRPEVASTFKVLRNVTVVLWSAYPVVWLIGSEGAGIVPLNIETLLFMVLDVSAKVGFGLILLRSRAIFGEAEAPEPSAGDGAAATSD"
)
BACTERIORHODOPSIN_TM = [(23, 42), (57, 75), (93, 109), (121, 140), (148, 167), (186, 204), (217, 236)]

BOVINE_RHODOPSIN = (  # P02699, 348 aa
    "MNGTEGPNFYVPFSNKTGVVRSPFEAPQYYLAEPWQFSMLAAYMFLLIMLGFPINFLTLYVTVQHKKLRTPLNYILLNLAVADLFMVFGGFTTTLYTSLHGYFVFGPTGCNLEGFFATLGGEIALWSLVVLAIERYVVVCKPMSNFRFGENHAIMGVAFTWVMALACAAPPLVGWSRYIPEGMQCSCGIDYYTPHEETNNESFVIYMFVVHFIIPLIVIFFCYGQLVFTVKEAAAQQQESATTQKAEKEVTRMVIIMVIAFLICWLPYAGVAFYIFTHQGSDFGPIFMTIPAFFAKTSAVYNPVIYIMMNKQFRNCMVTTLCCGKNPLGDDEASTTVSKTETSQVAPA"
)
BOVINE_RHODOPSIN_TM = [(37, 61), (74, 96), (111, 133), (153, 173), (203, 224), (253, 274), (287, 308)]

TM_PROTEINS = [
    ("Bacteriorhodopsin (P02945)", BACTERIORHODOPSIN, BACTERIORHODOPSIN_TM),
    ("Bovine rhodopsin (P02699)", BOVINE_RHODOPSIN, BOVINE_RHODOPSIN_TM),
]

MIN_OVERLAP = 10  # a predicted segment "finds" a helix if they share at least this many residues


def overlap(a, b):
    """Number of residues two (start, end) ranges have in common."""

    return max(0, min(a[1], b[1]) - max(a[0], b[0]) + 1)


def main_tm():
    
    print()
    print("Transmembrane helices (Kyte-Doolittle, window 19, threshold 1.6)")
    print("-" * 108)
    total_true = total_found = total_false = 0

    for name, seq, true_helices in TM_PROTEINS:
        predicted = [(h["start"], h["end"]) for h in predict_transmembrane_helices(seq)]
        found = [t for t in true_helices if any(overlap(t, p) >= MIN_OVERLAP for p in predicted)]
        extra = [p for p in predicted if not any(overlap(t, p) >= MIN_OVERLAP for t in true_helices)]
        total_true += len(true_helices)
        total_found += len(found)
        total_false += len(extra)
        missed = [t for t in true_helices if t not in found]
        print(f"{name:30s} UniProt helices: {len(true_helices)}   found: {len(found)}   false segments: {len(extra)}")
        print(f"{'':30s} predicted: {predicted}")
        if missed:
            print(f"{'':30s} missed: {missed}")

    print()
    print("Negative controls (soluble proteins; expected: no TM segments)")
    soluble_false = 0
    for name, seq, _expected, _why in BENCHMARKS:
        predicted = [(h["start"], h["end"]) for h in predict_transmembrane_helices(seq)]
        soluble_false += len(predicted)
        flag = "ok" if not predicted else f"FALSE ALARM {predicted}"
        print(f"{name:38s} {flag}")
    print("-" * 108)
    print(f"Real helices found: {total_found}/{total_true}   |   false segments in membrane proteins: {total_false}"
          f"   |   false segments in {len(BENCHMARKS)} soluble proteins: {soluble_false}")


if __name__ == "__main__":
    main()
    main_tm()
