import numpy as np

class MarginProbabilityModel:
    def __init__(self,regressor,calibrator):self.regressor=regressor;self.calibrator=calibrator
    def predict_proba(self,X):
        margin=self.regressor.predict(np.asarray(X)).reshape(-1,1)
        return self.calibrator.predict_proba(margin)

class ProbabilityBlend:
    def __init__(self, models, weights):
        self.models=models;self.weights=np.asarray(weights,dtype=float)/sum(weights)
    def predict_proba(self, X):
        probabilities=sum(weight*model.predict_proba(X) for model,weight in zip(self.models,self.weights))
        return probabilities

class FeatureSubsetModel:
    def __init__(self, model, indices):self.model=model;self.indices=list(indices)
    def predict_proba(self, X):return self.model.predict_proba(np.asarray(X)[:,self.indices])
