class PreferenceError(Exception):
    code = "preference_error"


class QuestionnaireGenerationFailed(PreferenceError):
    code = "questionnaire_generation_failed"


class QuestionnaireInvalid(PreferenceError):
    code = "questionnaire_invalid"


class AnswerRejected(PreferenceError):
    code = "answer_rejected"


class InterpretationFailed(PreferenceError):
    code = "interpretation_failed"


class PreferenceProposalInvalid(PreferenceError):
    code = "preference_proposal_invalid"


class ProfileRevisionStale(PreferenceError):
    code = "profile_revision_stale"


StaleProfileRevision = ProfileRevisionStale
PreferenceTuningError = PreferenceError


class PersistenceConflict(PreferenceError):
    code = "persistence_conflict"


class RetentionIntegrityError(PreferenceError):
    code = "retention_integrity_error"
