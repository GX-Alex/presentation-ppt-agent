#!/usr/bin/env python
"""简单启动脚本"""
import uvicorn
uvicorn.run("main:app", host="0.0.0.0", port=8002, reload=False)
