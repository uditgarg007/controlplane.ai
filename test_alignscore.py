from alignscore import AlignScore

print("Loading AlignScore model (this may take a minute)...")
try:
    scorer = AlignScore(
        model="roberta-base",
        batch_size=16,
        device="cpu",
        ckpt_path="./checkpoints/AlignScore-base.ckpt",
        evaluation_mode="nli_sp"
    )
    print("Model loaded successfully!")

    print("\nTesting scoring...")
    score = scorer.score(
        contexts=["The sky is blue."],
        claims=["The sky has a blue color."]
    )

    print(f"Test Score: {score}")

except Exception as e:
    print(f"Error loading or running AlignScore: {e}")
    print("\nMake sure the download has completely finished before running this script.")
