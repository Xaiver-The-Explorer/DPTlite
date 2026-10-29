"""
biology.py
----------
The actual science: reference data + pure functions for sequence and protein analysis, core to the CS50 final project.

This is the "model" in MVC terms, and it has no dependencies on Flask, databases, or the web at all. It just takes strings in and returns
numbers/strings/dictionaries out, which makes it easy to test and easy to read on its own. Basic college-level STEM knowledge is assumed.

IMPORTANT: These are bioinformatic heuristics, not lab-grade predictions. They do not replace TMHMM, PSIPRED, or IUPred.
"""

import re


# ================================================================================
# 1. Biology Background: reference data for codon table and amino acid properties.
# ================================================================================

# Valid letters for protein sequences (20 standard amino acids). 'X' and '*' are allowed in input but not considered valid for analysis.
VALID_PROTEIN_LETTERS = set("ACDEFGHIKLMNPQRSTVWY")

# Standard genetic code. Keys are DNA codons written 5'->3'. '*' means STOP. RNA condons are translated by swapping U -> T before lookup.
CODON_TABLE = {
    "TTT": "F", "TTC": "F", "TTA": "L", "TTG": "L",
    "CTT": "L", "CTC": "L", "CTA": "L", "CTG": "L",
    "ATT": "I", "ATC": "I", "ATA": "I", "ATG": "M",
    "GTT": "V", "GTC": "V", "GTA": "V", "GTG": "V",
    "TCT": "S", "TCC": "S", "TCA": "S", "TCG": "S",
    "CCT": "P", "CCC": "P", "CCA": "P", "CCG": "P",
    "ACT": "T", "ACC": "T", "ACA": "T", "ACG": "T",
    "GCT": "A", "GCC": "A", "GCA": "A", "GCG": "A",
    "TAT": "Y", "TAC": "Y", "TAA": "*", "TAG": "*",
    "CAT": "H", "CAC": "H", "CAA": "Q", "CAG": "Q",
    "AAT": "N", "AAC": "N", "AAA": "K", "AAG": "K",
    "GAT": "D", "GAC": "D", "GAA": "E", "GAG": "E",
    "TGT": "C", "TGC": "C", "TGA": "*", "TGG": "W",
    "CGT": "R", "CGC": "R", "CGA": "R", "CGG": "R",
    "AGT": "S", "AGC": "S", "AGA": "R", "AGG": "R",
    "GGT": "G", "GGC": "G", "GGA": "G", "GGG": "G",
}

# Complementary base pairs for DNA and RNA. Keys are bases, values are their complements.
DNA_COMPLEMENT = {"A": "T", "T": "A", "C": "G", "G": "C", "N": "N"}
RNA_COMPLEMENT = {"A": "U", "U": "A", "C": "G", "G": "C", "N": "N"}

# Kyte & Doolittle (1982) hydropathy scale. Higher means more hydrophobic.
HYDROPATHY_SCALE = {
    "A": 1.8, "R": -4.5, "N": -3.5, "D": -3.5, "C": 2.5,
    "Q": -3.5, "E": -3.5, "G": -0.4, "H": -3.2, "I": 4.5,
    "L": 3.8, "K": -3.9, "M": 1.9, "F": 2.8, "P": -1.6,
    "S": -0.8, "T": -0.7, "W": -0.9, "Y": -1.3, "V": 4.2,
}

# Simplified physiological-pH charge. Histidine is left at 0 by default since it's only weakly protonated (pKa ~6); everything else is +-1.
RESIDUE_CHARGE = {"D": -1, "E": -1, "K": 1, "R": 1}

# Average residue mass in Daltons (mass of the amino acid minus one water, i.e. the mass it contributes once it's in a peptide chain).
RESIDUE_MASS = {
    "G": 57.05, "A": 71.08, "S": 87.08, "P": 97.12, "V": 99.13,
    "T": 101.10, "C": 103.14, "L": 113.16, "I": 113.16, "N": 114.10,
    "D": 115.09, "Q": 128.13, "K": 128.17, "E": 129.12, "M": 131.19,
    "H": 137.14, "F": 147.18, "R": 156.19, "Y": 163.18, "W": 186.21,
}

# Average water mass in Daltons (added once, for the two free ends of the chain).
WATER_MASS = 18.02

# Typical pKa values for N-terminal, C-terminal, and ionizable side chains. Used for the theoretical isoelectric point (pI) estimate.
PKA_N_TERM = 9.69
PKA_C_TERM = 2.34
PKA_SIDE_CHAIN = {
    "D": 3.65, "E": 4.25, "C": 8.33, "Y": 10.07,
    "H": 6.00, "K": 10.53, "R": 12.48,
}

# Chou-Fasman (1978) conformational propensities: helix (Pa), sheet (Pb), turn (Pt). Values above 1.00 favor that structure at a given residue.
CONFORMATIONAL_PROPENSITIES = {
    "A": (1.42, 0.83, 0.66), "R": (0.98, 0.93, 0.95), "N": (0.67, 0.89, 1.56),
    "D": (1.01, 0.54, 1.46), "C": (0.70, 1.19, 1.19), "Q": (1.11, 1.10, 0.98),
    "E": (1.51, 0.37, 0.74), "G": (0.57, 0.75, 1.56), "H": (1.00, 0.87, 0.95),
    "I": (1.08, 1.60, 0.47), "L": (1.21, 1.30, 0.59), "K": (1.16, 0.74, 1.01),
    "M": (1.45, 1.05, 0.60), "F": (1.13, 1.38, 0.60), "P": (0.57, 0.55, 1.52),
    "S": (0.77, 0.75, 1.43), "T": (0.83, 1.19, 0.96), "W": (1.08, 1.37, 0.96),
    "Y": (0.69, 1.47, 1.14), "V": (1.06, 1.70, 0.50),
}


# ===========================================================================
# 2. Input Handling: cleaning sequence data and auto-detecting sequence type.
# ===========================================================================

# Define sequence data cleaning
def clean_sequence_data(raw_text):
    """Strip FASTA headers, whitespace, and digits; uppercase the rest."""

    # Split the input text into lines and strip leading/trailing whitespace.
    lines = raw_text.strip().splitlines()

    # Filter out any lines that start with '>' (FASTA headers).
    kept = [ln for ln in lines if not ln.startswith(">")]

    # Join the remaining lines into a single string.
    seq = "".join(kept)

    # Remove any whitespace characters and digits from the sequence using a regular expression.
    seq = re.sub(r"[\s0-9]", "", seq)

    # Convert the sequence to uppercase to standardize it.
    return seq.upper()


# Define sequence type detection
def detect_sequence_type(seq):
    """
    Work out whether the cleaned sequence looks like DNA, RNA, or protein.
    Return (seq_type, invalid_chars) where seq_type is one of 'DNA', 'RNA', 'PROTEIN', or 'UNKNOWN' if it's a mix hard to classify.
    """

    # If the sequence is empty, return "EMPTY" and an empty set of invalid characters.
    if not seq:
        return "EMPTY", set()

    letters = set(seq)
    dna_letters = set("ACGTN")
    rna_letters = set("ACGUN")

    # Check if the sequence contains only valid DNA letters and does not contain 'U'.
    if letters <= dna_letters and "U" not in letters:
        return "DNA", set()

    # Check if the sequence contains only valid RNA letters and does not contain 'T'.
    if letters <= rna_letters and "T" not in letters:
        return "RNA", set()

    # Check if the sequence contains only valid protein letters or valid protein letters plus 'X' or '*'.
    if letters <= VALID_PROTEIN_LETTERS or letters <= (VALID_PROTEIN_LETTERS | {"X", "*"}):
        return "PROTEIN", set()

    # Not a clean match for anything: report the offending characters.
    allowed = dna_letters | rna_letters | VALID_PROTEIN_LETTERS | {"X", "*"}
    invalid = letters - allowed
    return "UNKNOWN", invalid


# ====================================================================================
# 3. Sequence Operations: translating, reverse-complementing, and analyzing sequences.
# ====================================================================================

# Define transformation of RNA to DNA
def to_dna(seq):
    """Return the sequence with any U swapped to T (RNA -> DNA alphabet)."""

    return seq.replace("U", "T")


# Define coding-strand transcription of DNA to RNA
def transcribe(dna_seq):
    """DNA -> RNA: swap T for U (coding-strand transcription, no reverse)."""

    return dna_seq.replace("T", "U")


# Define reverse complement of a sequence
def reverse_complement(seq, is_rna):
    """Return the reverse complement, in the same alphabet as the input."""

    # Select the appropriate complement table based on whether the sequence is RNA or DNA.
    table = RNA_COMPLEMENT if is_rna else DNA_COMPLEMENT

    # Generate the complemented sequence by looking up each base in the complement table. If a base is not found, use 'N' as a placeholder.
    complemented = "".join(table.get(base, "N") for base in seq)

    # Return the complemented sequence reversed to get the reverse complement.
    return complemented[::-1]


# Define translation of a DNA sequence into a protein sequence
def translate_frame(dna_seq):
    """
    Translate one reading frame, codon by codon, using the standard genetic code.
    Incomplete trailing codons are ignored. Stop codons are kept in the output as '*' so 6-frame views read naturally.
    """

    protein = []

    # Loop through the DNA sequence (start at index 0, step by 3) to extract codons. Stop when there are fewer than 3 bases left.
    for i in range(0, len(dna_seq) - 2, 3):
        codon = dna_seq[i:i + 3]
        # Look up the codon in the codon table. Use 'X' to represent an unknown codon (has an ambiguous base 'N').
        protein.append(CODON_TABLE.get(codon, "X"))

    # Return the translated protein sequence as a string.
    return "".join(protein)


# Define six-frame translation of a sequence
def six_frame_translation(seq, is_rna):
    """Build all 3 forward + 3 reverse reading frames as DNA-alphabet strings."""

    dna = to_dna(seq)
    rev = to_dna(reverse_complement(seq, is_rna))
    frames = []

    # Build the 3 forward reading frames by translating the DNA sequence starting at offsets 0, 1, and 2.
    for offset in range(3):
        frames.append({
            # Label the frame as "Forward frame 1", "Forward frame 2", or "Forward frame 3" based on the offset.
            "label": f"Forward frame {offset + 1}",
            # Translate the DNA sequence starting at the current offset and store the resulting protein sequence.
            "protein": translate_frame(dna[offset:]),
        })

    # Build the 3 reverse reading frames by translating the reverse complement DNA sequence starting at offsets 0, 1, and 2.
    for offset in range(3):
        frames.append({
            # Label the frame as "Reverse frame 1", "Reverse frame 2", or "Reverse frame 3" based on the offset.
            "label": f"Reverse frame {offset + 1}",
            # Translate the reverse complement DNA sequence starting at the current offset and store the resulting protein sequence.
            "protein": translate_frame(rev[offset:]),
        })

    # Return the list of all 6 (3 forward + 3 reverse) reading frames.
    return frames


# Define finding open reading frames (ORFs) in translated frames
def find_orfs(frames, min_len=20):
    """
    Scan every frame for ATG...STOP open reading frames (ORFs) and return them, longest first.
    This is a simple scan, not a full ORF-finder algorithm.
    """

    orfs = []

    # Loop through each translated reading frame to find ORFs.
    for frame in frames:
        # Get the protein sequence for the current frame.
        protein = frame["protein"]
        # Find the first occurrence of the start codon "M" (Methionine) in the protein sequence.
        start = protein.find("M")

        # Continue searching for ORFs in the protein sequence until no more start codons are found.
        while start != -1:
            # Find the next occurrence of a stop codon "*" after the start codon.
            stop = protein.find("*", start)
            # If no stop codon is found, set the end of the ORF to the end of the protein sequence.
            end = stop if stop != -1 else len(protein)
            # Extract the candidate ORF from the protein sequence, starting from the start codon to the stop codon (or end of sequence).
            candidate = protein[start:end]

            # If the candidate ORF meets the minimum length requirement, add it to the list of ORFs with relevant information.
            if len(candidate) >= min_len:
                orfs.append({
                    "frame": frame["label"],      # Label of the reading frame where the ORF was found.
                    "start_residue": start + 1,   # Start position of the ORF in the protein sequence (1-based index).
                    "length_aa": len(candidate),  # Length of the ORF in amino acids.
                    "protein": candidate,         # The amino acid sequence of the ORF.
                })
            # Find the next occurrence of the start codon "M" after the current start position to continue searching for ORFs.
            start = protein.find("M", start + 1)

    # Sort the list of ORFs by length in descending order so that the longest ORFs appear first.
    orfs.sort(key=lambda o: o["length_aa"], reverse=True)
    return orfs


# Define GC content calculation
def gc_content(seq):
    """Return the percentage of G/C bases in a DNA/RNA sequence."""

    # If the sequence is empty, return a GC content of 0.0 to avoid division by zero.
    if not seq:
        return 0.0

    # Count the number of G and C nucleotides in the sequence. Round percentage to two decimal places.
    gc = sum(1 for b in seq if b in "GC")
    return round(100 * gc / len(seq), 2)


# Define base composition calculation
def base_composition(seq):
    """Return a dictionary with the counts of each unique base in the sequence."""

    # Count the occurrences of each unique base in the sequence and return a dictionary with the counts.
    counts = {b: seq.count(b) for b in sorted(set(seq))}
    return counts


# ================================================================
# 4. Protein Analysis: hydrophobicity, charge, structure, domains.
# ================================================================

# Define cleaning of protein sequences
def clean_protein(protein):
    """Drop stop-codon markers and unknowns so downstream math stays clean."""

    return protein.replace("*", "").replace("X", "")


# Define amino acid composition calculation
def amino_acid_composition(protein):
    """Return a dictionary with the counts and percentages of each unique amino acid in the protein sequence."""

    # If the protein sequence is empty, set total to 1 to avoid division by zero in percentage calculations.
    total = len(protein) or 1

    # Create a dictionary that counts the occurrences of each unique amino acid in the protein sequence and calculates its percentage composition.
    return {
        aa: {"count": protein.count(aa), "percent": round(100 * protein.count(aa) / total, 1)}
        for aa in sorted(set(protein))
    }


# Define protein molecular weight calculation
def molecular_weight(protein):

    # If the protein sequence is empty, return a molecular weight of 0.0 to avoid unnecessary calculations.
    if not protein:
        return 0.0

    # Sum the average residue masses of each amino acid in the protein (110.0 for unknowns) and add the mass of water (for chain's two free ends).
    mass = sum(RESIDUE_MASS.get(aa, 110.0) for aa in protein) + WATER_MASS

    # Round the molecular weight to one decimal place and return it.
    return round(mass, 1)


# Define net charge calculation at a given pH
def net_charge_at_ph(protein, ph):
    """Henderson-Hasselbalch net charge of the protein at a given pH."""

    # Calculate the net charge of the protein at a given pH using the Henderson-Hasselbalch equation.
    charge = 1 / (1 + 10 ** (ph - PKA_N_TERM))   # N-terminus (+) protonation at low pH.
    charge -= 1 / (1 + 10 ** (PKA_C_TERM - ph))  # C-terminus (-) deprotonation at high pH.

    # Loop through each amino acid with ionizable side chain and calculate its contribution to the net charge based on its pKa value and the given pH.
    for aa, pka in PKA_SIDE_CHAIN.items():
        n = protein.count(aa)
        # For acidic residues (D, E, C, Y), calculate the negative contribution (deprotonation at high pH) to the net charge.
        if aa in ("D", "E", "C", "Y"):
            charge -= n / (1 + 10 ** (pka - ph))
        # For basic residues (H, K, R), calculate the positive contribution (protonation at low pH) to the net charge.
        else:
            charge += n / (1 + 10 ** (ph - pka))
    return charge


# Define theoretical isoelectric point (pI) estimation
def estimate_pi(protein, tolerance=0.01):
    """Binary-search the pH where net charge crosses zero (theoretical pI)."""

    # If the protein sequence is empty, return None to indicate that the pI cannot be estimated.
    if not protein:
        return None

    # Set the initial search range for pH values to be between 0.0 and 14.0, which covers the typical pH range for biological systems.
    low, high = 0.0, 14.0

    # Perform a binary search with 60 iterations to find the pH value where the net charge of the protein crosses zero (the theoretical pI).
    for _ in range(60):
        mid = (low + high) / 2
        # If the net charge is positive, it means the pI is at a higher pH, so the lower bound should be adjusted to the midpoint.
        if net_charge_at_ph(protein, mid) > 0:
            low = mid
        # If the net charge is negative or zero, it means the pI is at a lower pH, so the upper bound should be adjusted to the midpoint.
        else:
            high = mid
        # If the difference between the high and low bounds is less than the specified tolerance, break the loop as the pI has been sufficiently narrowed down.
        if high - low < tolerance:
            break

    # Round the estimated pI (the midpoint of the final search range) to two decimal places and return it.
    return round((low + high) / 2, 2)


# Define sliding window profile calculation for protein properties
def sliding_window_profile(protein, scale, window=9):
    """
    Average a per-residue scale (e.g. hydropathy) over a centered window.
    Returns one value per residue position, same length as the protein.
    """

    # The 'half' is calculated as half of the specified window size (integer division), which is 4 for a window of 9.
    n = len(protein)
    half = window // 2
    profile = []

    for i in range(n):
        # Determine the lower and upper bounds of the sliding window, ensuring they stay within the bounds of the protein sequence.
        lo, hi = max(0, i - half), min(n, i + half + 1)
        # Extract the chunk of the protein sequence that falls within the sliding window.
        chunk = protein[lo:hi]
        # Look up the scale value for each residue in the chunk, using a default value of 0.0 for any residues not found in the scale.
        values = [scale.get(aa, 0.0) for aa in chunk]
        # Calculate the average of the scale values in the chunk and round it to three decimal places before appending it to the profile list.
        profile.append(round(sum(values) / len(values), 3))
    return profile


# Define sliding window charge profile calculation
def charge_profile(protein, window=9):

    return sliding_window_profile(protein, RESIDUE_CHARGE, window)


# Define sliding window hydropathy profile calculation
def hydropathy_profile(protein, window=9):
    
    return sliding_window_profile(protein, HYDROPATHY_SCALE, window)


# Define secondary structure prediction using a simplified Chou-Fasman style approach
def predict_secondary_structure(protein, window=6):
    """
    Very simplified Chou-Fasman style prediction: for each residue,
    average the helix/sheet/turn propensities in a small window and pick whichever is highest (falling back to coil if nothing clears 1.0).
    Returns a string of the same length as the protein using H/E/C (Helix / Extended sheet / Coil), matching common secondary-structure notation.
    """

    # The 'half' is calculated as half of the specified window size (integer division), which is 3 for a window of 6.
    n = len(protein)
    half = window // 2
    structure = []

    for i in range(n):
        # Determine the lower and upper bounds of the sliding window, ensuring they stay within the bounds of the protein sequence.
        lo, hi = max(0, i - half), min(n, i + half + 1)
        # Extract the chunk of the protein sequence that falls within the sliding window.
        chunk = protein[lo:hi]
        # Look up the conformational propensities for each residue in the chunk, using default values of (1.0, 1.0, 1.0) for any residues not found.
        scores = [CONFORMATIONAL_PROPENSITIES.get(aa, (1.0, 1.0, 1.0)) for aa in chunk]
        # Calculate the average helix, sheet, and turn propensities over the scores in the chunk.
        avg_helix = sum(s[0] for s in scores) / len(scores)
        avg_sheet = sum(s[1] for s in scores) / len(scores)
        avg_turn = sum(s[2] for s in scores) / len(scores)
        # Determine which secondary structure has the highest average propensity and store it in 'best'.
        best = max(("H", avg_helix), ("E", avg_sheet), ("C", avg_turn), key=lambda t: t[1])
        # Append with a threshold: if the best propensity is greater than 1.0, use that structure; otherwise, default to "C" (coil).
        structure.append(best[0] if best[1] > 1.0 else "C")

    # Return the predicted secondary structure as a string of characters representing helix (H), extended sheet (E), and coil (C).
    return "".join(structure)


# Define summary of secondary structure composition
def structure_summary(structure_string):

    # If the structure string is empty, set total to 1 to avoid division by zero in percentage calculations.
    total = len(structure_string) or 1

    # Create a dictionary that calculates the percentage (rounded to one decimal place) of each secondary structure type in the structure string.
    return {
        "helix_percent": round(100 * structure_string.count("H") / total, 1),
        "sheet_percent": round(100 * structure_string.count("E") / total, 1),
        "coil_percent": round(100 * structure_string.count("C") / total, 1),
    }


# Define transmembrane helix prediction using a hydropathy window approach
def predict_transmembrane_helices(protein, window=19, threshold=1.6):
    """
    The classic Kyte-Doolittle hydropathy-plot rule (1982):
    slide a 19-residue window along the protein, and any window whose average hydropathy is above 1.6 is a likely membrane-spanning segment.
    Windows that overlap or touch are merged into one reported segment, so each segment is at least 19 residues long (the window itself) and
    covers the whole stretch of qualifying windows.
    """

    n = len(protein)

    # If the protein sequence is shorter than the specified window size, return an empty list as no transmembrane helices can be predicted.
    if n < window:
        return []

    # Every window start whose average clears the threshold.
    qualifying = []

    for start in range(n - window + 1):
        # Extract the chunk of the protein sequence that falls within the current sliding window.
        chunk = protein[start:start + window]
        # Calculate the average Kyte-Doolittle hydropathy score for the residues in the current window, using a default value of 0.0 for any residues not found.
        avg = sum(HYDROPATHY_SCALE.get(aa, 0.0) for aa in chunk) / window
        # If the average hydropathy of the current window exceeds the specified threshold, add the start position of the window to the list of qualifying windows.
        if avg > threshold:
            qualifying.append(start)

    # Merge windows that overlap or touch into segments [first residue, last residue].
    segments = []

    for start in qualifying:
        # Calculate the end position of the current window based on the start position and the specified window size.
        end = start + window - 1
        # If the current window overlaps or touches the last segment, extend the last segment's end position to include the current window.
        if segments and start <= segments[-1][1] + 1:
            segments[-1][1] = end
        # If the current window does not overlap or touch the last segment, create a new segment with the current start and end positions.
        else:
            segments.append([start, end])

    # Return a list of dictionaries representing the predicted transmembrane helices, with start and end positions (1-based) and length of each segment.
    return [
        {"start": s + 1, "end": e + 1, "length": e - s + 1}
        for s, e in segments
    ]


# Define signal peptide prediction using a hydrophobicity heuristic
def predict_signal_peptide(protein, search_window=30, core_len=6, threshold=1.5):
    """
    Very rough signal-peptide heuristic: look for a run of at least `core_len` consecutive hydrophobic residues (average Kyte–Doolittle
    hydropathy score > threshold) within the first `search_window` residues -- the classic "h-region" of a signal peptide.
    """

    # If the protein sequence is empty, return None to indicate that no signal peptide can be predicted.
    if not protein:
        return None

    # Limit the search to the first `search_window` residues of the protein sequence.
    region = protein[:search_window]

    # Ensure the loop runs only if the region is long enough to accommodate a chunk of length `core_len`.
    for i in range(0, max(0, len(region) - core_len + 1)):
        # Extract a chunk of the protein sequence of length `core_len` starting from the current index `i`.
        chunk = region[i:i + core_len]
        # Calculate the average Kyte-Doolittle hydropathy score for the residues in the chunk, using a default value of 0.0 for any residues not found.
        avg = sum(HYDROPATHY_SCALE.get(aa, 0.0) for aa in chunk) / len(chunk)
        # If the average hydropathy score exceeds the specified threshold, return it along with the start and end positions (1-based) of the signal peptide region.
        if avg > threshold:
            return {"start": i + 1, "end": i + core_len, "avg_hydropathy": round(avg, 2)}

    # If no chunk is hydrophobic enough within the search window, return None to indicate that no signal peptide is predicted.
    return None


# Uversky, Gillespie & Fink (2000) charge-hydropathy boundary:
#       <R> = 2.785 * <H> - 1.151
# <H> is the mean Kyte-Doolittle hydropathy rescaled to 0-1 (Arg = 0 ... Ile = 1), and <R> is the absolute value of the mean net charge per residue at pH 7.
# Both constants only make sense on that 0-1 hydropathy scale. A sequence whose <H> lies above the line is predicted compact/ordered; below it, disordered.
CH_SLOPE = 2.785
CH_INTERCEPT = 1.151

# A sequence whose <H> lands within this distance of the boundary is reported as "Borderline" instead of being forced onto one side. The width is a judgment
# call (it is NOT derived from data), kept as a named constant so it is easy to change. Here, 0.03 is 3% of the whole 0-1 hydropathy scale.
BORDERLINE_MARGIN = 0.03


# Define calculation of the charge-hydropathy boundary for a given absolute net charge
def ch_boundary(abs_net_charge):
    """The <H> a sequence needs to reach to sit on the 'ordered' side of the line."""

    return (abs_net_charge + CH_INTERCEPT) / CH_SLOPE


# Define order/disorder prediction using a simplified charge-hydropathy approach
def predict_order_disorder(protein):
    """
    Simplified whole-protein charge-hydropathy call, in the spirit of the Uversky et al. (2000) order/disorder plot.
    Highly charged, low-hydropathy sequences stay unfolded because their charge repulsion and lack of a hydrophobic core keep them from collapsing;
    hydrophobic sequences with little net charge collapse into a folded core. The net charge is the Henderson-Hasselbalch value at pH 7.0, averaged
    over the sequence length. Note: "margin" is <H> minus the boundary. Beyond +/- BORDERLINE_MARGIN the call is ordered or disordered; inside that
    band it is "Borderline", because the boundary line itself is only an approximate separator.
    """

    # If the protein sequence is empty, return a default result indicating that no order/disorder prediction can be made.
    if not protein:
        return {"call": "N/A", "verdict": "none", "mean_hydropathy": 0, "abs_net_charge": 0,
                "boundary": 0, "margin": 0, "borderline_margin": BORDERLINE_MARGIN}

    # Calculate the mean Kyte-Doolittle hydropathy score for the protein sequence, using a default value of 0.0 for any residues not found.
    mean_hydropathy = sum(HYDROPATHY_SCALE.get(aa, 0.0) for aa in protein) / len(protein)

    # Normalize the mean hydropathy score from -4.5..4.5 to a 0-1 scale, which makes it easier to compare with the absolute mean net charge.
    norm_hydropathy = (mean_hydropathy + 4.5) / 9.0

    # Calculate the absolute net charge per residue for the protein sequence at psychological pH 7.0, using the Henderson-Hasselbalch equation.
    abs_net_charge = abs(net_charge_at_ph(protein, 7.0)) / len(protein)

    # Calculate the boundary value based on the absolute net charge, which is used to determine whether the protein is likely ordered or disordered.
    boundary = ch_boundary(abs_net_charge)

    # Calculate the margin, which is the difference between the normalized hydropathy and the boundary value.
    margin = norm_hydropathy - boundary

    # If the margin is greater than or equal to the defined borderline margin, classify the protein as "ordered" and provide a corresponding call.
    if margin >= BORDERLINE_MARGIN:
        verdict, call = "ordered", "Likely ordered / folds into a domain"
    # If the margin is less than or equal to the negative of the defined borderline margin, classify the protein as "disordered" and provide a corresponding call.
    elif margin <= -BORDERLINE_MARGIN:
        verdict, call = "disordered", "Possibly disordered"
    # If the margin is within the defined borderline range, classify the protein as "borderline" and provide a corresponding call.
    else:
        verdict, call = "borderline", "Borderline: close to the order/disorder boundary"

    # Return a dictionary containing the order/disorder prediction results.
    return {
        "call": call,
        "verdict": verdict,                            # "ordered" / "borderline" / "disordered", for code to test
        "mean_hydropathy": round(norm_hydropathy, 3),
        "abs_net_charge": round(abs_net_charge, 3),
        "boundary": round(boundary, 3),
        "margin": round(margin, 3),
        "borderline_margin": BORDERLINE_MARGIN,
    }


# Define disorder profile calculation along the protein sequence
def disorder_profile(protein, window=15):
    """
    Positional order/disorder tendency along the sequence:
    the same charge-hydropathy rule applied inside a sliding window. The score is how far the window's <H> sits above (ordered, +) or below
    (disordered, -) the boundary. Applying the rule locally is an extension for the chart -- the published method classifies whole proteins
    -- and short windows are noisy. Window charge is the simple D/E = -1, K/R = +1 count.
    """

    # The 'half' is calculated as half of the specified window size (integer division), which is 7 for a window of 15.
    n = len(protein)
    half = window // 2
    scores = []

    # If the protein sequence is empty, return an empty list to indicate that no disorder profile can be calculated.
    if n == 0:
        return []

    for i in range(n):
        # Determine the lower and upper bounds of the sliding window, ensuring they stay within the bounds of the protein sequence.
        lo, hi = max(0, i - half), min(n, i + half + 1)
        # Extract the chunk of the protein sequence that falls within the sliding window.
        chunk = protein[lo:hi]
        # Calculate the mean Kyte-Doolittle hydropathy score for the residues in the chunk, using a default value of 0.0 for any residues not found.
        mean_hydropathy = sum(HYDROPATHY_SCALE.get(aa, 0.0) for aa in chunk) / len(chunk)
        # Normalize the mean hydropathy score from -4.5..4.5 to a 0-1 scale, which makes it easier to compare with the absolute mean net charge.
        norm_hydropathy = (mean_hydropathy + 4.5) / 9.0
        # Calculate the absolute net charge per residue for the chunk, using a default value of 0 for any residues not found.
        abs_net_charge = abs(sum(RESIDUE_CHARGE.get(aa, 0) for aa in chunk)) / len(chunk)
        # Append the difference between the normalized hydropathy and the boundary to the scores list, rounded to three decimal places.
        scores.append(round(norm_hydropathy - ch_boundary(abs_net_charge), 3))

    # Return the list of scores representing the positional order/disorder tendency along the protein sequence.
    return scores


# Define a comprehensive protein analysis that bundles various analyses into a single dictionary
def analyze_protein(protein):
    """Bundle every protein-level analysis into one JSON-friendly dictionary."""

    # Clean the protein sequence by removing stop-codon markers and unknown residues to ensure accurate downstream analyses.
    protein = clean_protein(protein)

    # Predict the secondary structure of the protein sequence using the simplified Chou-Fasman style approach.
    structure = predict_secondary_structure(protein)

    # Return a dictionary containing various analyses of the protein sequence.
    return {
        "length": len(protein),
        "sequence": protein,
        "composition": amino_acid_composition(protein),
        "molecular_weight_da": molecular_weight(protein),
        "theoretical_pi": estimate_pi(protein),
        "hydropathy_profile": hydropathy_profile(protein),
        "charge_profile": charge_profile(protein),
        "secondary_structure": structure,
        "structure_summary": structure_summary(structure),
        "transmembrane_helices": predict_transmembrane_helices(protein),
        "signal_peptide": predict_signal_peptide(protein),
        "order_disorder": predict_order_disorder(protein),
        "disorder_profile": disorder_profile(protein),
    }
