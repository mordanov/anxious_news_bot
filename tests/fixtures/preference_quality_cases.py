VALID_QUESTION_CASES = tuple(
    f"Which news coverage format do you prefer for dimension {index}?"
    for index in range(20)
)

CONSECUTIVE_DISTINCT_CASES = tuple(
    (
        f"Which local reporting style do you prefer for area {index}?",
        f"How much international analysis do you want for region {index}?",
    )
    for index in range(20)
)
