#!/bin/bash

# Path to the DesigniteJava.jar
DESIGNITE_JAR_PATH="./DesigniteJava.jar"

# Directory containing the project folders, provided as a command-line argument
PROJECTS_DIR="$1"

# Check if the project directory argument was provided
if [ -z "$PROJECTS_DIR" ]; then
    echo "Usage: $0 <projects_directory>"
    exit 1
fi

# Check if the DesigniteJava.jar exists
if [ ! -f "$DESIGNITE_JAR_PATH" ]; then
    echo "DesigniteJava.jar not found at path: $DESIGNITE_JAR_PATH"
    exit 1
fi

# Iterate over each folder in the projects directory
for PROJECT_FOLDER in "$PROJECTS_DIR"/*; do
    if [ -d "$PROJECT_FOLDER" ]; then
        # Extract the project name from the folder path
        PROJECT_NAME=$(basename "$PROJECT_FOLDER")
        
        # Define the output directory name
        OUTPUT_DIR="code_smells/${PROJECT_NAME}_smells"
        
        # Run the DesigniteJava tool
        echo "Processing project: $PROJECT_NAME"
        java -jar "$DESIGNITE_JAR_PATH" -i "$PROJECT_FOLDER" -o "$OUTPUT_DIR"
        
        echo "Output generated at: $OUTPUT_DIR"
    fi
done

echo "All projects processed."
