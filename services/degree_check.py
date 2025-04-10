from fastapi import FastAPI
from sentence_transformers import SentenceTransformer, util
import requests
import math

app = FastAPI()

# Load SBERT model
model = SentenceTransformer("all-mpnet-base-v2")

# Predefined degree rankings (local hierarchy)
degree_rank = {
    "PhD": 6,
    "MTech": 5, "ME": 5, "MSc": 4, "MCA": 3.2,
    "BTech": 3, "BE": 3, "BSc": 2, "BCA": 1, "Diploma": 0.5
}

# Synonyms for normalization
degree_synonyms = {
    "B.E.": "BE",
    "B.Sc.": "BSc",
    "M.Sc.": "MSc",
    "Master of Science": "MSc",
    "Bachelor of Technology": "BTech",
}

def normalize_degree(degree):
    """Normalize degree by removing dots, spaces, and handling synonyms."""
    degree = degree.replace(".", "").strip().lower()  # Convert to lowercase for consistency
    return degree_synonyms.get(degree, degree).lower()

def fetch_global_rank(degree):
    """Fetch degree hierarchy from Wikidata using SPARQL."""
    query = f"""
    SELECT ?degreeLabel ?parentLabel WHERE {{
      ?degree wdt:P31 wd:Q189533;  # Instance of academic degree
              rdfs:label "{degree}"@en.
      OPTIONAL {{ ?degree wdt:P279 ?parent. }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }}
    """
    url = "https://query.wikidata.org/sparql"
    headers = {"Accept": "application/json"}
    response = requests.get(url, headers=headers, params={"query": query})

    if response.status_code == 200:
        data = response.json()
        results = data.get("results", {}).get("bindings", [])
        
        parent_degrees = [entry["parentLabel"]["value"] for entry in results if "parentLabel" in entry]
        
        if parent_degrees:
            for parent in parent_degrees:
                if parent in degree_rank:
                    return degree_rank[parent]  # Assign parent's rank
    
    return None  # No known hierarchy

def get_degree_score(degree):
    """Returns predefined weight if known, else finds closest match."""
    degree = normalize_degree(degree)
    
    if degree in degree_rank:
        return degree_rank[degree]
    
    # Try fetching global equivalence
    global_rank = fetch_global_rank(degree)
    if global_rank is not None:
        return global_rank

    # Compute similarity with known degrees
    known_degrees = list(degree_rank.keys())
    emb_degree = model.encode(degree, convert_to_tensor=True)
    similarities = {d: util.pytorch_cos_sim(emb_degree, model.encode(d, convert_to_tensor=True)).item() for d in known_degrees}
    
    # Find best matching known degree
    best_match = max(similarities, key=similarities.get)
    
    # Adjust score based on similarity percentage
    return degree_rank[best_match] * similarities[best_match]

def degree_similarity(candidate_degree, job_requirement):
    """Computes similarity score between candidate and job degree."""
    candidate_score = get_degree_score(candidate_degree)
    job_score = get_degree_score(job_requirement)

    if job_score == 0:  # Avoid division by zero
        return 0

    degree_gap = abs(candidate_score - job_score)

    # Candidate has a lower degree → Apply a penalty
    if candidate_score < job_score:
        penalty = max(40, 100 - (degree_gap * 10))  # Min 40
        return round(penalty, 2)

    # Candidate has a higher degree → Apply a bonus
    if candidate_score > job_score:
        bonus = min(140, 100 + (degree_gap * 10))  # Max 140
        return round(bonus, 2)

    return 100  # Exact match

@app.get("/degree_similarity/")
def degree_similarity_api(candidate_degree: str, job_requirement: str):
    """API endpoint to compare degrees."""
    similarity_score = degree_similarity(candidate_degree, job_requirement)
    return {"Degree Similarity Score": similarity_score}

# To run the API, use: uvicorn degree_check:app --reload
# Call API in browser: http://127.0.0.1:8000/degree_similarity/?candidate_degree=BCA&job_requirement=Btech
