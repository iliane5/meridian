import numpy as np
import pandas as pd
from typing import List, Dict, Any, Tuple
from sklearn.preprocessing import StandardScaler
from umap import UMAP
import hdbscan
from transformers import AutoTokenizer, AutoModel
import torch
from concurrent.futures import ThreadPoolExecutor
from src.helpers import average_pool, process_story

def generate_embeddings(articles: List[Dict[str, Any]], batch_size: int = 32) -> np.ndarray:
    """Generate embeddings for a list of articles using a multilingual model"""
    # Load model and tokenizer
    model_name = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModel.from_pretrained(model_name)
    
    # Move model to GPU if available
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = model.to(device)
    
    # Process articles in batches
    embeddings = []
    for i in range(0, len(articles), batch_size):
        batch = articles[i:i + batch_size]
        texts = [article["title"] + " " + article["content"] for article in batch]
        
        # Tokenize and move to device
        inputs = tokenizer(texts, padding=True, truncation=True, max_length=512, return_tensors="pt")
        inputs = {k: v.to(device) for k, v in inputs.items()}
        
        # Generate embeddings
        with torch.no_grad():
            outputs = model(**inputs)
            batch_embeddings = average_pool(outputs.last_hidden_state, inputs["attention_mask"])
            embeddings.extend(batch_embeddings.cpu().numpy())
    
    return np.array(embeddings)

def optimize_clustering_params(embeddings: np.ndarray) -> Tuple[Dict[str, Any], float]:
    """Find optimal UMAP and HDBSCAN parameters using grid search"""
    # Scale embeddings
    scaler = StandardScaler()
    scaled_embeddings = scaler.fit_transform(embeddings)
    
    # Define parameter grid
    umap_params = {
        "n_neighbors": [5, 10, 15],
        "min_dist": [0.0, 0.1, 0.2],
        "n_components": [5, 10, 15]
    }
    
    hdbscan_params = {
        "min_cluster_size": [5, 10, 15],
        "min_samples": [3, 5, 7],
        "cluster_selection_epsilon": [0.0, 0.1, 0.2]
    }
    
    best_score = -1
    best_params = {}
    
    # Grid search
    for n_neighbors in umap_params["n_neighbors"]:
        for min_dist in umap_params["min_dist"]:
            for n_components in umap_params["n_components"]:
                # Apply UMAP
                umap = UMAP(
                    n_neighbors=n_neighbors,
                    min_dist=min_dist,
                    n_components=n_components,
                    random_state=42
                )
                reduced_embeddings = umap.fit_transform(scaled_embeddings)
                
                for min_cluster_size in hdbscan_params["min_cluster_size"]:
                    for min_samples in hdbscan_params["min_samples"]:
                        for epsilon in hdbscan_params["cluster_selection_epsilon"]:
                            # Apply HDBSCAN
                            clusterer = hdbscan.HDBSCAN(
                                min_cluster_size=min_cluster_size,
                                min_samples=min_samples,
                                cluster_selection_epsilon=epsilon
                            )
                            labels = clusterer.fit_predict(reduced_embeddings)
                            
                            # Calculate score (number of clusters with more than 3 points)
                            n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
                            score = n_clusters
                            
                            if score > best_score:
                                best_score = score
                                best_params = {
                                    "umap": {
                                        "n_neighbors": n_neighbors,
                                        "min_dist": min_dist,
                                        "n_components": n_components
                                    },
                                    "hdbscan": {
                                        "min_cluster_size": min_cluster_size,
                                        "min_samples": min_samples,
                                        "cluster_selection_epsilon": epsilon
                                    }
                                }
    
    return best_params, best_score

def cluster_articles(articles: List[Dict[str, Any]], params: Dict[str, Any]) -> Tuple[np.ndarray, List[int]]:
    """Cluster articles using UMAP and HDBSCAN with given parameters"""
    # Generate embeddings
    embeddings = generate_embeddings(articles)
    
    # Scale embeddings
    scaler = StandardScaler()
    scaled_embeddings = scaler.fit_transform(embeddings)
    
    # Apply UMAP
    umap = UMAP(
        n_neighbors=params["umap"]["n_neighbors"],
        min_dist=params["umap"]["min_dist"],
        n_components=params["umap"]["n_components"],
        random_state=42
    )
    reduced_embeddings = umap.fit_transform(scaled_embeddings)
    
    # Apply HDBSCAN
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=params["hdbscan"]["min_cluster_size"],
        min_samples=params["hdbscan"]["min_samples"],
        cluster_selection_epsilon=params["hdbscan"]["cluster_selection_epsilon"]
    )
    labels = clusterer.fit_predict(reduced_embeddings)
    
    return reduced_embeddings, labels

def process_clusters(articles: List[Dict[str, Any]], labels: List[int]) -> List[Dict[str, Any]]:
    """Process clusters into a list of stories"""
    # Group articles by cluster
    clusters = {}
    for i, label in enumerate(labels):
        if label not in clusters:
            clusters[label] = []
        clusters[label].append(articles[i])
    
    # Process each cluster
    stories = []
    for label, cluster_articles in clusters.items():
        if label == -1:  # Skip noise
            continue
        
        if len(cluster_articles) < 3:  # Skip small clusters
            continue
        
        # Create story object
        story = {
            "articles": cluster_articles,
            "articles_ids": [article["id"] for article in cluster_articles],
            "size": len(cluster_articles)
        }
        stories.append(story)
    
    return stories

def process_stories_parallel(stories: List[Dict[str, Any]], events: List[Dict[str, Any]], max_workers: int = 4) -> List[Dict[str, Any]]:
    """Process stories in parallel using a thread pool"""
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(process_story, story, events) for story in stories]
        results = []
        for future in futures:
            try:
                result, usage = future.result()
                results.append(result)
            except Exception as e:
                print(f"Error processing story: {e}")
                continue
    
    return results 