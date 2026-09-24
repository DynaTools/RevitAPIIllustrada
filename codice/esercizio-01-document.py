print("Título       :", doc.Title)
print("Caminho      :", doc.PathName or "(não salvo)")
print("Compartilhado:", doc.IsWorkshared)
print("Vista ativa  :", doc.ActiveView.Name)
