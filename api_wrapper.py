from fastapi import FastAPI, HTTPException, Depends, Request, UploadFile, File
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
import cognee
from cognee.modules.search.types.SearchType import SearchType
from cognee.modules.settings.get_current_settings import get_current_settings
from cognee.modules.settings.save_llm_config import save_llm_config, LLMConfig
from cognee.modules.settings.save_vector_db_config import save_vector_db_config
import os
from typing import Dict, Any, List, Optional
import logging
import tempfile
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Cognee API Wrapper", version="1.0.0")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security
security = HTTPBearer()
API_KEY = os.getenv("API_KEY", "your-secret-api-key")

def verify_api_key(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if credentials.credentials != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return credentials.credentials

@app.get("/health")
async def health_check(api_key: str = Depends(verify_api_key)):
    return {"status": "healthy", "service": "cognee-api"}

@app.post("/api/add")
async def add_data(request: Request, api_key: str = Depends(verify_api_key)):
    try:
        data = await request.json()
        text_data = data.get("text", "") or data.get("data", "")
        dataset_name = data.get("dataset", None) or data.get("dataset_name", None)
        
        if not text_data:
            raise HTTPException(status_code=400, detail="Text data is required")
        
        # Add data to cognee with optional dataset
        if dataset_name:
            result = await cognee.add(text_data, dataset_name)
        else:
            result = await cognee.add(text_data)
        
        return {
            "status": "success",
            "message": "Data added successfully",
            "dataset": dataset_name,
            "result": result
        }
    except Exception as e:
        logger.error(f"Error adding data: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.post("/api/cognify")
async def cognify_data(request: Request, api_key: str = Depends(verify_api_key)):
    try:
        # Get request body
        body = await request.json() if request.headers.get("content-type") == "application/json" else {}
        datasets = body.get("datasets", None)
        
        # Process the data - if datasets specified, use them, otherwise process all
        if datasets:
            result = await cognee.cognify(datasets=datasets)
        else:
            result = await cognee.cognify()
        
        return {
            "status": "success",
            "message": "Data processed successfully",
            "result": result
        }
    except Exception as e:
        logger.error(f"Error processing data: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.post("/api/search")
async def search_data(request: Request, api_key: str = Depends(verify_api_key)):
    try:
        data = await request.json()
        query = data.get("query", "")
        search_type = data.get("search_type", "GRAPH_COMPLETION")
        datasets = data.get("datasets", None)
        top_k = data.get("top_k", 5)
        
        if not query:
            raise HTTPException(status_code=400, detail="Query is required")
        
        # Validate search_type
        try:
            search_type_enum = SearchType[search_type]
        except KeyError:
            available_types = [t.value for t in SearchType]
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid search_type. Available types: {available_types}"
            )
        
        # Search in cognee with specified parameters
        result = await cognee.search(
            query_text=query,
            query_type=search_type_enum,
            datasets=datasets,
            top_k=top_k
        )
        
        return {
            "status": "success",
            "query": query,
            "search_type": search_type,
            "datasets": datasets,
            "top_k": top_k,
            "results": result
        }
    except Exception as e:
        logger.error(f"Error searching data: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

# Dataset Management Endpoints
@app.post("/api/datasets")
async def create_dataset(request: Request, api_key: str = Depends(verify_api_key)):
    try:
        data = await request.json()
        dataset_name = data.get("dataset_name", "") or data.get("name", "")
        
        if not dataset_name:
            raise HTTPException(status_code=400, detail="Dataset name is required")
        
        # Add some dummy data to create dataset (cognee creates datasets when adding data)
        result = await cognee.add("Dataset initialization", dataset_name)
        
        return {
            "status": "success",
            "message": f"Dataset '{dataset_name}' created successfully",
            "dataset": dataset_name,
            "result": str(result)
        }
    except Exception as e:
        logger.error(f"Error creating dataset: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/api/datasets")
async def list_datasets(api_key: str = Depends(verify_api_key)):
    try:
        from cognee.api.v1.datasets.datasets import datasets
        dataset_list = await datasets.list_datasets()
        return {
            "status": "success",
            "datasets": [{
                "id": str(dataset.id),
                "name": dataset.name,
                "created_at": str(dataset.created_at) if hasattr(dataset, 'created_at') else None
            } for dataset in dataset_list]
        }
    except Exception as e:
        logger.error(f"Error listing datasets: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.delete("/api/datasets/{dataset_name}")
async def delete_dataset(dataset_name: str, api_key: str = Depends(verify_api_key)):
    try:
        from cognee.api.v1.datasets.datasets import datasets
        result = await datasets.delete_dataset(dataset_name)
        return {
            "status": "success",
            "message": f"Dataset '{dataset_name}' deleted successfully",
            "result": str(result)
        }
    except Exception as e:
        logger.error(f"Error deleting dataset: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

# File Upload Endpoints
@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...), dataset: Optional[str] = None, api_key: str = Depends(verify_api_key)):
    try:
        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix) as tmp_file:
            content = await file.read()
            tmp_file.write(content)
            tmp_file_path = tmp_file.name
        
        try:
            # Add file to cognee
            if dataset:
                result = await cognee.add(tmp_file_path, dataset)
            else:
                result = await cognee.add(tmp_file_path)
            
            return {
                "status": "success",
                "message": f"File '{file.filename}' uploaded and processed successfully",
                "filename": file.filename,
                "dataset": dataset,
                "result": result
            }
        finally:
            # Clean up temporary file
            os.unlink(tmp_file_path)
            
    except Exception as e:
        logger.error(f"Error uploading file: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

# Configuration Endpoints
@app.post("/api/config")
async def update_config(request: Request, api_key: str = Depends(verify_api_key)):
    try:
        data = await request.json()
        
        # Update cognee configuration based on config type
        if "llm" in data:
            llm_config = LLMConfig(**data["llm"])
            await save_llm_config(llm_config)
        if "vector_db" in data:
            await save_vector_db_config(data["vector_db"])
        
        return {
            "status": "success",
            "message": "Configuration updated successfully",
            "config": data
        }
    except Exception as e:
        logger.error(f"Error updating config: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/api/config")
async def get_config(api_key: str = Depends(verify_api_key)):
    try:
        config = get_current_settings()
        return {
            "status": "success",
            "config": config
        }
    except Exception as e:
        logger.error(f"Error getting config: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

# Visualization Endpoints
@app.get("/api/visualize")
async def start_visualization(api_key: str = Depends(verify_api_key)):
    try:
        from cognee.api.v1.visualize.start_visualization_server import visualization_server
        # Start visualization server on port 8080
        result = visualization_server(8080)
        return {
            "status": "success",
            "message": "Visualization server started on port 8080",
            "result": "Server started successfully"
        }
    except Exception as e:
        logger.error(f"Error starting visualization: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/api/visualize/graph")
async def visualize_graph(dataset: Optional[str] = None, api_key: str = Depends(verify_api_key)):
    try:
        from cognee.api.v1.visualize.visualize import visualize_graph
        import os
        import tempfile
        
        # Create a temporary file for the visualization
        temp_dir = tempfile.gettempdir()
        html_file = os.path.join(temp_dir, "graph_visualization.html")
        
        result = await visualize_graph(html_file)
        
        return {
            "status": "success",
            "dataset": dataset,
            "visualization_file": html_file,
            "message": "Graph visualization generated successfully"
        }
    except Exception as e:
        logger.error(f"Error visualizing graph: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

# Cleanup Endpoints
@app.post("/api/prune")
async def prune_data(request: Request, api_key: str = Depends(verify_api_key)):
    try:
        data = await request.json()
        
        # Get prune parameters
        prune_type = data.get("type", "data")  # "data" or "system"
        
        if prune_type == "system":
            result = await cognee.prune.prune_system()
        else:
            result = await cognee.prune.prune_data()
        
        return {
            "status": "success",
            "message": f"Pruned {prune_type} successfully",
            "result": result
        }
    except Exception as e:
        logger.error(f"Error pruning data: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

# Health Check endpoint removed - using /health instead

# Search Types Info
@app.get("/api/search/types")
async def get_search_types(api_key: str = Depends(verify_api_key)):
    try:
        search_types = [{
            "name": search_type.name,
            "value": search_type.value
        } for search_type in SearchType]
        
        return {
            "status": "success",
            "search_types": search_types
        }
    except Exception as e:
        logger.error(f"Error getting search types: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
